"""AI layer for the after-hours front desk (Agent 9, Phase 4).

Two model jobs, both "model states / code decides":

  route_message — classify ONE patient message into intents[] (a single
  message can carry several — "refill my BP meds and book my checkup" is two,
  FR-A2 / PRD Edge Case 16), each with a short summary the handler receives
  as its payload. The tool also reports emergency_symptoms_detected (a second
  net behind the deterministic red-flag regex, never a replacement — FR-A6)
  and a nullable mandatory_escalation_category (PRD Edge Case 12). Code
  validates every intent against the registry and every category against the
  hardcoded mandatory list before acting.

  answer_from_articles — write the FAQ reply using ONLY the retrieved
  knowledge articles. If they don't contain the answer it says so and the
  caller opens an unanswered_question staff task — the model is never allowed
  to improvise a clinic fact (FR-A5).

The orchestration loop (handle_frontdesk_message) keeps the safety order
fixed: deterministic red_flag_check FIRST (before any model call), then the
router, then emergency / mandatory-category handling, then per-intent
dispatch through the Phase 2 registry — which still enforces the auth gate,
so a protected intent from an anonymous caller is queued exactly as if it
had been named explicitly. A router failure never blocks the patient: it
degrades to a manual_review staff task.
"""

import json
import logging

from langsmith import traceable

from core.ai import call_tool, strict_tool
from core.safety import find_red_flags, red_flag_check
from frontdesk.models import PatientSession
from frontdesk.services import (
    MANDATORY_ESCALATION_PRIORITIES,
    REGISTRY,
    create_staff_task,
    dispatch_intent,
)

log = logging.getLogger("frontdesk")

# The schema enum is derived from the registry, so adding an agent there
# automatically teaches the router about it.
INTENTS = list(REGISTRY)
MANDATORY_CATEGORIES = list(MANDATORY_ESCALATION_PRIORITIES)


# -- the router tool (FR-A2/A4/A6/A7) ----------------------------------------------

ROUTE_MESSAGE = strict_tool(
    "route_message",
    "Classify one patient message for a medical clinic's after-hours front "
    "desk. A single message can carry SEVERAL intents (e.g. a refill AND a "
    "booking) -- report each one, in the order the patient raised them, "
    "with a one-line summary of what they want for that intent. "
    "Set emergency_symptoms_detected=true if the message describes symptoms "
    "that could be life-threatening (chest pain, breathing trouble, stroke "
    "signs, heavy bleeding, suicidal thoughts...), even when phrased "
    "indirectly. Set mandatory_escalation_category when the message is a "
    "mental-health crisis, suspected stroke, a dispute about an insurance "
    "claim/charge, or a request about a controlled substance (opioids, "
    "benzodiazepines such as alprazolam/Xanax, sleep medication, stimulants) "
    "-- null otherwise. Intent meanings: appointment = book/reschedule/cancel/view "
    "visits; refill = medication running out or a repeat prescription; "
    "referral_status = where a referral TO A SPECIALIST stands; pa_status = "
    "whether INSURANCE HAS APPROVED (prior authorization for) a test, scan, "
    "procedure, or medication; care_gap = preventive care that may be due "
    "(screenings, vaccines, annual checks); symptoms = the patient describes "
    "how they feel and wants guidance; faq = questions about the clinic "
    "itself (hours, parking, fees, insurance accepted, test prep, records, "
    "portal help); other = anything else (billing callbacks, feedback, "
    "profile changes).",
    {
        "intents": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "enum": INTENTS},
                    "summary": {
                        "type": "string",
                        "description": "One line: what the patient wants for this "
                                       "intent (medication name, question text, ...).",
                    },
                },
                "required": ["intent", "summary"],
                "additionalProperties": False,
            },
        },
        "emergency_symptoms_detected": {
            "type": "boolean",
            "description": "True if the message describes possibly life-threatening symptoms.",
        },
        "mandatory_escalation_category": {
            "type": ["string", "null"],
            "enum": MANDATORY_CATEGORIES + [None],
            "description": "The mandatory human-escalation category, or null.",
        },
    },
    ["intents", "emergency_symptoms_detected", "mandatory_escalation_category"],
)

ROUTER_PROMPT = (
    "You are the intent router for a medical clinic's after-hours front "
    "desk. You never answer the patient yourself -- you only classify what "
    "they need so the right specialist agent can handle it. Report every "
    "distinct request in the message, err on the side of caution for "
    "emergency symptoms, and never invent an intent the message doesn't "
    "contain."
)


@traceable(name="route_message", run_type="chain")
def route_message(text: str, history: list[dict] | None = None) -> dict:
    """One forced tool call: patient text (+ recent turns) -> routing decision."""
    messages = list(history or []) + [{"role": "user", "content": text}]
    return call_tool(system=ROUTER_PROMPT, messages=messages, tool=ROUTE_MESSAGE)


# -- grounded FAQ answering (FR-A5) --------------------------------------------------

ANSWER_FROM_ARTICLES = strict_tool(
    "answer_from_articles",
    "Answer the patient's question using ONLY the provided clinic articles. "
    "If the articles contain the answer, write a short, friendly reply that "
    "states it plainly. If they do NOT contain the answer, set "
    "answered=false and leave answer empty -- never guess or use outside "
    "knowledge about clinics in general. Never add facts (prices, times, "
    "policies) that the articles don't state.",
    {
        "answered": {
            "type": "boolean",
            "description": "True only if the articles actually contain the answer.",
        },
        "answer": {
            "type": "string",
            "description": "The reply, built only from the articles; '' when answered=false.",
        },
    },
    ["answered", "answer"],
)

ANSWER_FAQ_PROMPT = (
    "You answer patients' questions about a medical clinic using only the "
    "reference articles you are given. You never rely on general knowledge "
    "and never invent clinic facts. If the articles don't answer the "
    "question, you say so via answered=false."
)


@traceable(name="answer_faq", run_type="chain")
def answer_faq(question: str, articles: list) -> dict:
    """One forced tool call: question + retrieved articles -> grounded answer."""
    return call_tool(
        system=ANSWER_FAQ_PROMPT,
        messages=[{"role": "user", "content": json.dumps({
            "question": question,
            "articles": [{"title": a.title, "body": a.body} for a in articles],
        })}],
        tool=ANSWER_FROM_ARTICLES,
    )


# -- the orchestration loop (FR-A2/A6, PRD after-hours journey) -----------------------

def _emergency_result(session: PatientSession, text: str) -> dict:
    """The emergency short-circuit: triage's script, and a human is alerted.

    An authenticated session raises a triage EscalationAlert and pages
    on-call (Agent 3's machinery, reused). An anonymous one can't — the
    alert table requires a patient — so the front desk's own queue gets a
    critical task instead; the patient-facing script is identical either
    way and never asks follow-ups."""
    from triage.models import EscalationAlert
    from triage.services import notify_on_call
    from triage.views import EMERGENCY_MESSAGE

    flags = find_red_flags(text)
    if session.patient is not None:
        alert = EscalationAlert.objects.create(
            patient=session.patient, source_agent="frontdesk",
            category="emergency", priority="high",
            summary=f"Front-desk emergency: {text[:300]!r}"
                    + (f" (red flags: {flags})" if flags else " (model-detected)"),
        )
        notify_on_call(alert)
    else:
        create_staff_task(
            session, "manual_review", priority="critical",
            summary=f"EMERGENCY from unauthenticated session: {text[:300]!r}",
        )
    return {"status": "emergency", "reply": EMERGENCY_MESSAGE,
            "ui_hints": {"emergency": True}}


def _combine(results: list[dict]) -> dict:
    """Fold per-intent results into one coherent response (PRD: 'I've sent
    your refill... and here are slots for your checkup'). Duplicate replies
    (e.g. two intents queued behind the same auth prompt) collapse to one."""
    replies = []
    for result in results:
        reply = result.get("reply", "")
        if reply and reply not in replies:
            replies.append(reply)
    statuses = [r.get("status") for r in results]
    if "auth_required" in statuses:
        status = "auth_required"
    elif "escalated" in statuses:
        status = "escalated"
    else:
        status = "completed"
    return {"status": status, "reply": " ".join(replies), "results": results}


@traceable(name="handle_frontdesk_message", run_type="chain")
def handle_frontdesk_message(session: PatientSession, text: str,
                             history: list[dict] | None = None) -> dict:
    """Free text in, one coherent front-desk response out.

    Safety order is fixed: (1) deterministic red-flag screen before any
    model call; (2) the router; (3) the model's emergency flag — a second
    net for indirect phrasings; (4) mandatory escalation category; (5) each
    remaining intent dispatched through the registry in order (the auth
    gate still applies per intent). A router failure degrades to a
    manual_review task — the patient always gets an answer."""
    if red_flag_check(text):
        return _emergency_result(session, text)

    try:
        routed = route_message(text, history)
    except Exception:
        log.exception("[FRONTDESK ROUTER] unavailable; degrading to manual review")
        task = create_staff_task(session, "manual_review",
                                 summary=f"Router unavailable for: {text[:300]!r}")
        return {"status": "escalated", "staff_task_id": task.id,
                "reply": "I'm having trouble understanding requests right now — "
                         "a team member will follow up with you."}

    if routed.get("emergency_symptoms_detected"):
        return _emergency_result(session, text)

    results = []
    category = routed.get("mandatory_escalation_category")
    if category in MANDATORY_ESCALATION_PRIORITIES:  # code decides, not the model
        task = create_staff_task(session, category, summary=text[:300])
        results.append({"status": "escalated", "staff_task_id": task.id,
                        "reply": "This needs a person — I've flagged it to our "
                                 "team as a priority."})
    elif category:
        log.warning("[FRONTDESK ROUTER] ignored unknown category %r", category)

    intents = [item for item in (routed.get("intents") or [])
               if item.get("intent") in REGISTRY]  # code decides, not the model
    if not intents and not results:
        intents = [{"intent": "other", "summary": text[:300]}]

    for item in intents:
        summary = item.get("summary") or text
        # handlers read "question" (faq) or "text" (everything else)
        results.append(dispatch_intent(session, item["intent"],
                                       {"text": summary, "question": summary}))

    return _combine(results)
