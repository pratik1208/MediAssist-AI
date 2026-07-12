"""AI layer for the outreach agent (Agent 7, Phase 4).

Two forced tool calls, same "the model states, the code decides" split as
every other agent's AI layer:

  classify_response — a patient's raw SMS/email reply -> intent (book /
  snooze / opt_out / question / unclear) + snooze_until (if a timeframe was
  given) + question_text. The single worst failure mode here is
  misclassifying an opt-out as anything else, so the prompt is explicit
  that ambiguous-toward-opt_out always resolves to opt_out. Belt and
  braces: outreach.services also runs a deterministic keyword check for the
  standard carrier STOP/UNSUBSCRIBE/CANCEL keywords BEFORE ever calling
  this, so opt-out compliance doesn't depend on the model (or the network)
  being available at all.

  render_outreach_message_body — campaign goal + language -> one message
  body, no greeting/name (the caller prepends "Hi {name}," itself so the
  one truly personal touch never needs its own API call). services.py
  caches the result per (language, goal) so a 5,000-patient wave makes at
  most a handful of calls, not one per patient (NFR-9).
"""

import json

from langsmith import traceable

from core.ai import call_tool, strict_tool

# -- FR-O5: classify an inbound reply -----------------------------------------

CLASSIFY_RESPONSE = strict_tool(
    "classify_response",
    "Classify a patient's reply to a clinic outreach message (e.g. a "
    "flu-shot reminder). intent is exactly one of: book (wants to schedule, "
    "or agrees to be contacted to book), snooze (wants a reminder later and "
    "gives or clearly implies a timeframe), opt_out (wants to stop being "
    "contacted at all -- 'stop', 'unsubscribe', 'stop texting me', 'leave "
    "me alone', 'take me off this list', etc.), question (asks something "
    "and needs an answer before deciding), unclear (anything that doesn't "
    "confidently fit the above). If a message could plausibly be read as "
    "either opt_out or something else, always choose opt_out -- continuing "
    "to contact someone who asked to stop is far worse than the reverse.",
    {
        "intent": {
            "type": "string",
            "enum": ["book", "snooze", "opt_out", "question", "unclear"],
            "description": "The single best-fit category, per the rules above.",
        },
        "snooze_until": {
            "type": ["string", "null"],
            "description": "ISO date (YYYY-MM-DD) to resume outreach, resolved against "
                           "'today' in the context. Only set when intent='snooze' AND a "
                           "timeframe was stated or clearly implied; null otherwise.",
        },
        "question_text": {
            "type": ["string", "null"],
            "description": "The patient's question, verbatim or lightly paraphrased. Only "
                           "set when intent='question'; null otherwise.",
        },
    },
    ["intent", "snooze_until", "question_text"],
)

CLASSIFY_RESPONSE_PROMPT = (
    "You classify a patient's SMS/email reply to a clinic outreach "
    "campaign message. You only ever pick one of book/snooze/opt_out/"
    "question/unclear. You never invent a snooze date beyond what the "
    "message states or clearly implies, and you always resolve doubt "
    "toward opt_out over any other category."
)


@traceable(name="classify_response", run_type="chain")
def classify_response(text: str, today: str) -> dict:
    """One forced tool call: raw reply text -> structured intent."""
    return call_tool(
        system=CLASSIFY_RESPONSE_PROMPT,
        messages=[{"role": "user", "content": json.dumps({"message": text, "today": today})}],
        tool=CLASSIFY_RESPONSE,
    )


# -- FR-O4: per-(language, goal) message body ---------------------------------

RENDER_OUTREACH_MESSAGE = strict_tool(
    "render_outreach_message",
    "Write ONE short outreach message body for a clinic campaign, in the "
    "requested language, suitable for SMS/email/voice-script use. Do NOT "
    "include a greeting or the patient's name -- the caller adds 'Hi "
    "{name},' itself. Ground the message only in the stated clinical goal; "
    "never add a clinical claim, diagnosis, or promise beyond it. End with "
    "an implicit invitation to reply (the caller doesn't append anything "
    "else).",
    {
        "body": {
            "type": "string",
            "description": "The message body only (no greeting/name), in the target language.",
        },
    },
    ["body"],
)

RENDER_MESSAGE_PROMPT = (
    "You write short, friendly clinic outreach message bodies (SMS/email/"
    "voice-script length) in the requested language, based only on the "
    "stated clinical goal. No greeting, no patient name, no medical advice "
    "beyond the goal itself."
)


@traceable(name="render_outreach_message", run_type="chain")
def render_outreach_message_body(clinical_goal: str, language: str) -> dict:
    """One forced tool call: campaign goal + language -> a reusable body."""
    return call_tool(
        system=RENDER_MESSAGE_PROMPT,
        messages=[{"role": "user", "content": json.dumps({
            "clinical_goal": clinical_goal, "language": language,
        })}],
        tool=RENDER_OUTREACH_MESSAGE,
    )
