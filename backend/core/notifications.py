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
