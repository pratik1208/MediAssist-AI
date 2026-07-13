"""Phase 1 model tests: __str__/admin display helpers, the one-session-per-
conversation constraint, and that seeded knowledge articles are actually
findable through the Postgres full-text vector (the whole point of the
search_vector column)."""

import datetime

import pytest
from django.contrib.postgres.search import SearchQuery
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone

from core.models import Conversation, Patient
from frontdesk.admin import PatientSessionAdmin
from frontdesk.models import IntentRoute, KnowledgeArticle, PatientSession, StaffTask

pytestmark = pytest.mark.django_db


@pytest.fixture
def patient(db):
    return Patient.objects.create(
        first_name="Rahul", last_name="Sharma", contact_number="9876543210",
        dob=datetime.date(1990, 5, 17), registration_status="complete",
    )


@pytest.fixture
def session(db):
    conversation = Conversation.objects.create(channel="web", started_at=timezone.now())
    return PatientSession.objects.create(conversation=conversation, channel="web")


def test_session_str_before_and_after_auth(session, patient):
    assert "unauthenticated" in str(session)
    session.patient = patient
    session.authenticated = True
    assert f"patient #{patient.id}" in str(session)


def test_one_session_per_conversation(session):
    with pytest.raises(IntegrityError):
        PatientSession.objects.create(conversation=session.conversation, channel="web")


def test_intent_route_str_and_inline_count(session):
    IntentRoute.objects.create(session=session, intent="refill", target_agent="refills")
    route = IntentRoute.objects.create(session=session, intent="faq", target_agent="knowledge")
    assert str(route) == "faq -> knowledge (routed)"
    assert PatientSessionAdmin(PatientSession, None).route_count(session) == 2


def test_staff_task_str(session, patient):
    task = StaffTask.objects.create(
        session=session, patient=patient, category="insurance_dispute",
        priority="high", summary="Patient disputes a co-pay charge.",
    )
    assert str(task) == "[high] insurance_dispute (open)"


def test_task_survives_session_deletion(session, patient):
    task = StaffTask.objects.create(
        session=session, patient=patient, category="manual_review",
        summary="needs a human",
    )
    session.conversation.delete()  # cascades to the session
    task.refresh_from_db()
    assert task.session is None  # SET_NULL: the queue entry survives


def test_seed_knowledge_is_idempotent_and_searchable():
    call_command("seed_knowledge")
    count = KnowledgeArticle.objects.count()
    assert count >= 15
    call_command("seed_knowledge")
    assert KnowledgeArticle.objects.count() == count

    # the GIN-backed vector actually retrieves: ask like a patient would
    hits = KnowledgeArticle.objects.filter(search_vector=SearchQuery("parking"))
    assert any("locations" in a.title.lower() for a in hits)
    hits = KnowledgeArticle.objects.filter(search_vector=SearchQuery("fasting blood test"))
    assert any("Fasting" in a.title for a in hits)
