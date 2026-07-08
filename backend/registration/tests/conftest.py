import datetime

import pytest

from core.models import Patient

DOB = datetime.date(1990, 5, 17)


@pytest.fixture(autouse=True)
def _no_langsmith_tracing(monkeypatch):
    """Keep test runs out of the real LangSmith project."""
    monkeypatch.setenv("LANGSMITH_TRACING", "false")


@pytest.fixture
def rahul(db):
    return Patient.objects.create(
        first_name="Rahul",
        last_name="Sharma",
        contact_number="+91 98765 43210",
        dob=DOB,
        registration_status="complete",
    )
