"""Front-desk orchestration logic (Agent 9, Phase 2) — no AI yet.

Three deterministic pillars the Phase 4 router will stand on:

  * The AUTH GATE (FR-A3, NFR-2): a session starts anonymous. Intents that
    touch patient data are QUEUED, not answered, until the patient proves
    who they are with DOB + OTP (Agent 2's machinery, reused wholesale —
    same codes, same hashing, same dev shortcut). Absolutely no
    patient-specific data crosses the gate: even "that DOB doesn't match"
    is reported identically to "no such patient".

  * The AGENT REGISTRY (FR-A2/A4): one declarative dict mapping each intent
    to its target agent and handler. Adding an agent is one line. Phase 2
    handlers are deliberately modest read-only summaries / hand-offs; Phase
    4 upgrades them to full conversational delegation without touching the
    dispatch mechanics. Every dispatch writes an IntentRoute row, so a
    multi-intent conversation stays auditable end to end (FR-A8).

  * The KNOWLEDGE LAYER (FR-A5): Postgres full-text over KnowledgeArticle
    IS the retrieval layer. FAQ answers are allowed pre-auth — clinic hours
    are not patient data.

Plus the "human needed" queue (FR-A7): certain categories are hardcoded as
mandatory escalations that ALWAYS create a StaffTask at fixed priority —
mental health crisis, suspected stroke, complex insurance dispute,
controlled-substance refill (PRD Edge Case 12).
"""

import logging
import re
from dataclasses import dataclass
from typing import Callable

from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F
from django.utils import timezone

from core.models import AuditEvent, Conversation, Message, Patient
from frontdesk.models import IntentRoute, KnowledgeArticle, PatientSession, StaffTask
from registration.services import create_otp, verify_otp

# Channels with no signed session token to correlate by -- SMS/WhatsApp
# replies are matched to an existing session via PatientSession.channel_identifier
# instead (Phase 6 channel adapter).
_TOKENLESS_CHANNELS = {"sms", "whatsapp"}

log = logging.getLogger("frontdesk")


def _audit(patient, action: str, payload: dict) -> None:
    if patient is None:
        return  # AuditEvent requires a patient; anonymous events go to logs
    AuditEvent.objects.create(
        actor_type="agent", actor_id="frontdesk", patient=patient,
        action=action, payload=payload,
    )


# -- FR-A3 / NFR-2: the auth gate ------------------------------------------------

# One neutral message for EVERY identification failure. Distinguishing "no
# such phone number" from "DOB doesn't match" would leak who is registered.
_AUTH_FAILED = "We couldn't verify those details."


def start_authentication(session: PatientSession, contact_number: str, dob) -> dict:
    """Step 1 of the gate: the patient claims an identity (phone + DOB) and,
    if it checks out, an OTP goes to THEIR phone. The candidate id is
    stashed in the conversation's scratch state, never returned. The reply
    is identical whether the phone is unknown or the DOB mismatches."""
    patient = Patient.objects.filter(contact_number=contact_number.strip()).first()
    if patient is None or str(patient.dob) != str(dob):
        return {"ok": False, "message": _AUTH_FAILED}

    create_otp(patient, "sms")
    context = session.conversation.agent_context or {}
    context["auth_candidate_id"] = patient.id
    session.conversation.agent_context = context
    session.conversation.save(update_fields=["agent_context"])
    return {"ok": True, "message": "We've sent a verification code to your phone."}


def authenticate_session(session: PatientSession, dob, otp: str) -> dict:
    """Step 2: DOB + OTP against the stashed candidate. On success the
    session is bound to the patient and any intents queued behind the gate
    become dispatchable (the caller runs resume_pending_intents). On any
    failure the session stays anonymous and the reply stays neutral."""
    candidate_id = (session.conversation.agent_context or {}).get("auth_candidate_id")
    patient = Patient.objects.filter(id=candidate_id).first() if candidate_id else None
    if patient is None or str(patient.dob) != str(dob):
        return {"ok": False, "message": _AUTH_FAILED}

    ok, reason = verify_otp(patient, otp)
    if not ok:
        log.info("[FRONTDESK AUTH] OTP failure for session %s: %s", session.id, reason)
        return {"ok": False, "message": _AUTH_FAILED}

    session.patient = patient
    session.authenticated = True
    session.save(update_fields=["patient", "authenticated"])
    _audit(patient, "frontdesk.session_authenticated",
           {"session_id": session.id, "channel": session.channel})
    return {"ok": True, "message": "You're verified."}


# -- FR-A7 / Edge Case 12: the "human needed" queue -------------------------------

# category -> priority. These four are MANDATORY escalations: no automated
# flow may absorb them (PRD Edge Case 12), and their priority is not a
# judgment call.
MANDATORY_ESCALATION_PRIORITIES = {
    "mental_health": "critical",
    "stroke": "critical",
    "insurance_dispute": "high",
    "controlled_substance": "high",
}
_DEFAULT_PRIORITIES = {
    "unanswered_question": "normal",
    "manual_review": "normal",
}


def create_staff_task(session: PatientSession | None, category: str,
                      priority: str | None = None, summary: str = "") -> StaffTask:
    """Create a queue entry for a human. Mandatory categories always get
    their fixed priority — a caller-supplied priority cannot downgrade
    them."""
    if category in MANDATORY_ESCALATION_PRIORITIES:
        priority = MANDATORY_ESCALATION_PRIORITIES[category]
    else:
        priority = priority or _DEFAULT_PRIORITIES.get(category, "normal")

    patient = session.patient if session else None
    task = StaffTask.objects.create(
        session=session, patient=patient, category=category,
        priority=priority, summary=summary or f"{category} raised via front desk",
    )
    _audit(patient, "frontdesk.staff_task_created",
           {"task_id": task.id, "category": category, "priority": priority})
    log.info("[FRONTDESK TASK] #%s %s (%s)", task.id, category, priority)
    return task


# -- FR-A5: the knowledge layer ---------------------------------------------------

def _ranked_by(sq: SearchQuery, limit: int) -> list:
    return list(
        KnowledgeArticle.objects
        .annotate(rank=SearchRank(F("search_vector"), sq))
        .filter(search_vector=sq)
        .order_by("-rank")[:limit]
    )


def search_knowledge(query: str, limit: int = 3):
    """Postgres full-text retrieval over the article corpus.

    Two passes: websearch parsing first (all terms must hit — precise for
    phrasings like "are you open on sundays?"), then an any-term OR pass,
    because patients phrase questions with verbs the articles never use
    ("do you TAKE Star Health" vs the article's "we accept..."), and rank
    still puts the right article first. Empty from both passes means "we
    genuinely don't know" — the caller turns that into an
    unanswered_question staff task rather than an improvised clinic fact."""
    hits = _ranked_by(SearchQuery(query, search_type="websearch"), limit)
    if hits:
        return hits

    or_query = None
    for term in re.findall(r"[A-Za-z0-9]+", query):
        sq = SearchQuery(term)
        or_query = sq if or_query is None else or_query | sq
    return _ranked_by(or_query, limit) if or_query is not None else []


# -- FR-A2/A4: the agent registry --------------------------------------------------
# Phase 2 handlers: deterministic read-only summaries and hand-offs. Each
# takes (session, payload) and returns a JSON-able dict with at least
# {"reply": ...}. Phase 4 swaps richer conversational handlers in; the
# registry shape and dispatch mechanics stay identical.

def _handle_appointment(session, payload):
    from scheduling.models import Appointment
    upcoming = (
        Appointment.objects
        .filter(patient=session.patient, status="booked",
                start_time__gte=timezone.now())
        .order_by("start_time")
    )
    return {
        "reply": "Here are your upcoming appointments." if upcoming
                 else "You have no upcoming appointments. I can help you book one.",
        "appointments": [{
            "id": a.id, "doctor": a.doctor.name,
            "start_time": a.start_time.isoformat(), "reason": a.reason,
        } for a in upcoming],
    }


def _handle_refill(session, payload):
    from refills.models import Prescription
    active = Prescription.objects.filter(patient=session.patient, status="active")
    controlled = [p for p in active if p.is_controlled_substance]
    if controlled and not [p for p in active if not p.is_controlled_substance]:
        # only controlled meds -> a human, always (Edge Case 12)
        task = create_staff_task(session, "controlled_substance",
                                 summary="Refill request for a controlled substance.")
        return {"reply": "A team member has to handle refills for this medication; "
                         "we've queued your request.", "staff_task_id": task.id}
    return {
        "reply": "These are your active medications; tell me which one to refill."
                 if active else "I don't see any active prescriptions on your chart.",
        "prescriptions": [{
            "id": p.id, "medication": p.medication_name,
            "refills_left": max(p.refills_allowed - p.refills_used, 0),
            "controlled": p.is_controlled_substance,
        } for p in active],
    }


def _handle_referral_status(session, payload):
    from referrals.models import Referral
    referrals = Referral.objects.filter(patient=session.patient).order_by("-id")[:5]
    return {
        "reply": "Here's where your referrals stand." if referrals
                 else "You have no referrals on file.",
        "referrals": [{"id": r.id, "specialty": r.specialty, "status": r.status}
                      for r in referrals],
    }


def _handle_pa_status(session, payload):
    from priorauth.models import AuthorizationRequest
    auths = (
        AuthorizationRequest.objects
        .filter(order__patient=session.patient)
        .select_related("order")
        .order_by("-id")[:5]
    )
    return {
        "reply": "Here's the status of your insurance authorizations." if auths
                 else "You have no authorization requests on file.",
        "authorizations": [{"id": a.id, "status": a.status,
                            "order_type": a.order.order_type} for a in auths],
    }


def _handle_care_gap(session, payload):
    from caregaps.services import open_gaps_for
    offers = open_gaps_for(session.patient)
    return {
        "reply": "You're due for some preventive care — want me to book it?"
                 if offers else "You're all caught up on preventive care. 🎉",
        "care_gaps": offers,
    }


def _handle_symptoms(session, payload):
    # Full triage is a guided conversation (Agent 3 owns it); the front desk
    # hands off rather than re-implementing the protocol flow.
    return {
        "reply": "Let's go through a few questions about your symptoms.",
        "handoff": "triage",
    }


def _handle_faq(session, payload):
    query = (payload or {}).get("question") or (payload or {}).get("text") or ""
    articles = search_knowledge(query)
    if not articles:
        task = create_staff_task(session, "unanswered_question",
                                 summary=f"No knowledge-base answer for: {query!r}")
        return {"reply": "I don't have that answer on hand — I've asked the team "
                         "to get back to you.", "staff_task_id": task.id}

    # Phase 4: the model phrases the answer FROM the retrieved articles only
    # (FR-A5). It may also conclude the articles don't actually answer the
    # question — that's an honest hand-off, not a failure. If the model is
    # unreachable, fall back to the top article verbatim: never block on AI.
    try:
        from frontdesk.ai import answer_faq  # local: services must import cleanly without the AI stack
        result = answer_faq(query, articles)
        if not result.get("answered"):
            task = create_staff_task(session, "unanswered_question",
                                     summary=f"Articles retrieved but none answer: {query!r}")
            return {"reply": "I don't have that answer on hand — I've asked the "
                             "team to get back to you.", "staff_task_id": task.id}
        reply = result["answer"]
    except Exception:
        log.exception("[FRONTDESK FAQ] model unavailable; replying with the top article")
        reply = articles[0].body

    return {
        "reply": reply,
        "articles": [{"id": a.id, "title": a.title} for a in articles],
    }


def _handle_other(session, payload):
    summary = (payload or {}).get("summary") or (payload or {}).get("text") \
        or "Unclassified front-desk request."
    task = create_staff_task(session, "manual_review", summary=summary)
    return {"reply": "I've passed this to our team — they'll follow up.",
            "staff_task_id": task.id}


@dataclass(frozen=True)
class AgentRoute:
    target_agent: str
    handler: Callable
    requires_auth: bool = True  # patient data is the default; opt OUT explicitly


# The orchestration heart. Adding an agent is one line (FR-A2/A4).
REGISTRY: dict[str, AgentRoute] = {
    "appointment":     AgentRoute("scheduling", _handle_appointment),
    "refill":          AgentRoute("refills", _handle_refill),
    "referral_status": AgentRoute("referrals", _handle_referral_status),
    "pa_status":       AgentRoute("priorauth", _handle_pa_status),
    "care_gap":        AgentRoute("caregaps", _handle_care_gap),
    "symptoms":        AgentRoute("triage", _handle_symptoms),
    "faq":             AgentRoute("knowledge", _handle_faq, requires_auth=False),
    "other":           AgentRoute("staff", _handle_other, requires_auth=False),
}


def dispatch_intent(session: PatientSession, intent: str, payload: dict | None = None) -> dict:
    """Route one intent through the registry.

    Pre-auth, a protected intent is QUEUED on the session (no IntentRoute
    row — nothing was routed, and no agent saw it) and the caller is told to
    start the auth flow. Every actual dispatch writes an IntentRoute row and
    settles it to completed/escalated (FR-A8)."""
    route = REGISTRY.get(intent)
    if route is None:
        route = REGISTRY["other"]
        intent = "other"

    if route.requires_auth and not session.authenticated:
        pending = list(session.pending_intents or [])
        pending.append({"intent": intent, "payload": payload or {}})
        session.pending_intents = pending
        session.save(update_fields=["pending_intents"])
        return {"status": "auth_required",
                "reply": "I can help with that as soon as I've verified your "
                         "identity. What's your registered phone number and "
                         "date of birth?"}

    record = IntentRoute.objects.create(
        session=session, intent=intent, target_agent=route.target_agent,
        payload=payload or {},
    )
    try:
        result = route.handler(session, payload or {})
    except Exception:
        log.exception("[FRONTDESK DISPATCH] %s handler failed", intent)
        task = create_staff_task(session, "manual_review",
                                 summary=f"Automated handling of a {intent!r} request failed.")
        record.status = "escalated"
        record.save(update_fields=["status"])
        return {"status": "escalated", "staff_task_id": task.id,
                "reply": "Something went wrong on our side — a team member will "
                         "pick this up."}

    record.status = "escalated" if result.get("staff_task_id") else "completed"
    record.save(update_fields=["status"])
    return {"status": record.status, **result}


def resume_pending_intents(session: PatientSession) -> list[dict]:
    """After the gate opens: dispatch everything the patient asked for while
    anonymous, in the order they asked, then clear the queue."""
    pending = list(session.pending_intents or [])
    if not pending or not session.authenticated:
        return []
    session.pending_intents = []
    session.save(update_fields=["pending_intents"])
    return [dispatch_intent(session, item.get("intent", "other"), item.get("payload"))
            for item in pending]


# -- Phase 6: channel adapters ("one front door for everything") ------------------

def _channel_history(session: PatientSession, limit: int = 10) -> list[dict]:
    rows = (Message.objects
            .filter(conversation=session.conversation, role__in=["Patient", "Assistant"])
            .order_by("-id")[:limit])
    return [{"role": "user" if m.role == "Patient" else "assistant", "content": m.content}
            for m in reversed(rows)]


def handle_channel_message(channel: str, sender: str, text: str) -> dict:
    """Route an inbound SMS/WhatsApp reply that Agent 7's webhook couldn't
    match to a running campaign (FR-A8's "one front door" -- a provider
    reply outside a campaign must still reach the front desk, not a 404).

    Provider messages carry no signed session token, so the sender's raw
    address is the correlation key: the same phone number's next message
    resumes the SAME session (including its auth state and any queued
    intents), rather than starting over each time. The auth gate itself is
    untouched -- arriving from a known number is not proof of DOB, so a
    protected intent still gets challenged exactly as it would over web
    chat (PRD Edge Case 12 must survive every entry point, not just one).
    """
    if channel not in _TOKENLESS_CHANNELS:
        raise ValueError(f"channel must be one of {sorted(_TOKENLESS_CHANNELS)}")

    session = (
        PatientSession.objects
        .filter(channel=channel, channel_identifier=sender)
        .order_by("-id")
        .first()
    )
    if session is None:
        conversation = Conversation.objects.create(
            channel=channel, started_at=timezone.now(),
            agent_context={"active_agent": "frontdesk"},
        )
        session = PatientSession.objects.create(
            conversation=conversation, channel=channel, channel_identifier=sender,
        )

    history = _channel_history(session)
    Message.objects.create(conversation=session.conversation, role="Patient", content=text)

    from frontdesk.ai import handle_frontdesk_message  # local: mirrors the chat view's import
    outcome = handle_frontdesk_message(session, text, history=history)

    Message.objects.create(conversation=session.conversation, role="Assistant",
                           content=outcome.get("reply", ""))
    return {"session_id": session.id, "conversation_id": session.conversation_id, **outcome}
