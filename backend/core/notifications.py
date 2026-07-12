"""core.notifications — one door for every outbound message (SPEC_Core §4.3).

Every SMS / email / WhatsApp / voice message the whole system sends goes through
notify(). Because it's the ONLY door, the opt-out rule (NFR-8) is enforced here
once, globally — no agent can accidentally message someone who opted out.

Dev uses ConsoleProvider (prints to stdout). Twilio/SendGrid/etc. later just
implement the same send() method.
"""

from core.models import Patient, SentNotification

# Channels that go to a phone number vs. an email address.
_PHONE_CHANNELS = ("sms", "voice", "whatsapp")
_CHANNEL_ORDER = ("sms", "email", "voice", "whatsapp")


class ConsoleProvider:
    """Dev provider: just prints. Real providers implement the same send()."""

    def send(self, channel: str, recipient: str, content: str) -> str:
        print(f"[{channel}] -> {recipient}: {content}")
        return "console-msg-id"


provider = ConsoleProvider()


# Very simple template store. Real templates (with translations) come later.
_TEMPLATES: dict[str, str] = {
    "appointment_booked": "Hi {name}, your appointment with Dr. {doctor} is confirmed for {start}.",
    "appointment_cancelled": "Hi {name}, your appointment on {start} has been cancelled.",
    "registration_complete": "Hi {name}, your registration is complete! You can now book an appointment — just tell us your symptoms or a preferred time.",
    "refill_paused": "Hi {name}, your refill request for {medication} is on hold: {reason}. We'll help you resolve this — reply here or call the clinic.",
    "refill_sent": "Hi {name}, your refill for {medication} was approved and sent to {pharmacy}.",
    "refill_ready": "Hi {name}, your {medication} is ready for pickup at {pharmacy}.",
    "refill_rejected": "Hi {name}, your refill request for {medication} was not approved: {reason}. Please contact the clinic to discuss next steps.",
    "triage_booking_offer": "Hi {name}, based on your assessment you should see a doctor {urgency}. Would you like me to book an appointment for you?",
    "refill_visit_booking_offer": "Hi {name}, your doctor would like to see you before refilling {medication}. Would you like me to book an appointment?",
    "referral_missed_appointment": "Hi {name}, we noticed you missed your {specialty} specialist appointment. Would you like to reschedule?",
    "priorauth_approved": "Hi {name}, your insurance authorization for {treatment} was approved. We'll be in touch to schedule it.",
    "priorauth_denied": "Hi {name}, your insurance authorization for {treatment} was not approved: {reason}. Please contact the clinic to discuss next steps.",
    "priorauth_booking_offer": "Hi {name}, your {treatment} was approved by your insurance. Would you like me to help you book an appointment for it?",
    "outreach_message": "Hi {name}, {reason}. Reply to let us know, or call the clinic to book. Reply STOP to opt out.",
    # "appointment_reminder": "Hi {name}, your appointment is on {date}.",
}


def render_template(template: str, context: dict, language: str = "en") -> str:
    """render_template() looks up a message template, replaces placeholders like {name} with values from context, and safely falls back to the original text if the template or required values are missing."""

    body = _TEMPLATES.get(template, template)
    try:
        return body.format(**context)
    except (KeyError, IndexError):
        return body


def notify(patient: Patient, template: str, context: dict, channel: str | None = None) -> SentNotification | None:
    """Send one message to a patient, respecting their opt-out preferences.

    Returns the SentNotification row, or None if the patient opted out of the
    chosen channel (in which case nothing is sent).
    """
    prefs = patient.communication_preferences or {}

    # If no channel was requested, pick the first one the patient allows.
    if channel is None:
        channel = next((c for c in _CHANNEL_ORDER if prefs.get(c)), "sms")

    # Opt-out enforced HERE, globally (NFR-8). An explicit False means "no".
    if prefs.get(channel) is False:
        return None

    content = render_template(template, context, patient.preferred_language)
    recipient = patient.contact_number if channel in _PHONE_CHANNELS else patient.email

    n = SentNotification.objects.create(
        patient=patient,
        channel=channel,
        recipient=recipient,
        rendered_content=content,
        status="queued",
    )
    n.provider_message_id = provider.send(channel, n.recipient, content)
    n.status = "sent"
    n.save(update_fields=["provider_message_id", "status"])
    return n
