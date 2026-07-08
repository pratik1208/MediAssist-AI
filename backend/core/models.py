from django.db import models

# Create your models here.


class Specialty(models.TextChoices):
    GENERAL_MEDICINE = "General Medicine", "General Medicine"
    CARDIOLOGY = "Cardiology", "Cardiology"
    DERMATOLOGY = "Dermatology", "Dermatology"
    PEDIATRICS = "Pediatrics", "Pediatrics"
    ORTHOPEDICS = "Orthopedics", "Orthopedics"
    GYNECOLOGY = "Gynecology", "Gynecology"
    NEUROLOGY = "Neurology", "Neurology"
    PSYCHIATRY = "Psychiatry", "Psychiatry"
    OPHTHALMOLOGY = "Ophthalmology", "Ophthalmology"
    ENT = "ENT", "ENT"
    GASTROENTEROLOGY = "Gastroenterology", "Gastroenterology"
    ENDOCRINOLOGY = "Endocrinology", "Endocrinology"
    PULMONOLOGY = "Pulmonology", "Pulmonology"
    UROLOGY = "Urology", "Urology"
    ONCOLOGY = "Oncology", "Oncology"
    NEPHROLOGY = "Nephrology", "Nephrology"
    RHEUMATOLOGY = "Rheumatology", "Rheumatology"
    INFECTIOUS_DISEASE = "Infectious Disease", "Infectious Disease"
    ALLERGY_IMMUNOLOGY = "Allergy & Immunology", "Allergy & Immunology"
    EMERGENCY_MEDICINE = "Emergency Medicine", "Emergency Medicine"

    class Meta:
        db_table = "patient_specialty"


class Patient(models.Model):
    LANGUAGE_CHOICES = [
        ("en", "English"),
        ("hi", "Hindi"),
        ("mr", "Marathi"),
        ("kn", "Kannada"),
        ("ta", "Tamil"),
        ("te", "Telugu"),
        ("gu", "Gujarati"),
        ("bn", "Bengali"),
        ("ml", "Malayalam"),
        ("pa", "Punjabi"),
    ]
    REGISTRATION_CHOICES = [("in_process", "in_process"), ("verified", "verified"), ("duplicate_detected", "duplicate_detected"), ("complete", "complete")]
    id = models.AutoField(primary_key=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    # store contact numbers as strings to preserve leading zeros and allow +/()-characters
    contact_number = models.CharField(max_length=15)
    dob = models.DateField()
    email = models.EmailField(null=True)
    address = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        {
            "line1": "",
            "line2": "",
            "city": "",
            "state": "",
            "zip": ""
        }
        """,
    )
    emergency_contact = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
        {
            "Contact 1": "",
            "Contact 2": "",
            "Contact 3": "",
        }
        """,
    )
    preferred_language = models.CharField(max_length=10, choices=LANGUAGE_CHOICES, default="en")
    preferred_pharmacy = models.CharField(max_length=255, null=True, blank=True)
    registration_status = models.CharField(max_length=20, choices=REGISTRATION_CHOICES)
    identity_verified = models.BooleanField(default=False)
    communication_preferences = models.JSONField(
        default=dict,
        blank=True,
        help_text="""
                    {
                    "sms": false,
                    "email": true,
                    "voice": true,
                    "whatsapp": false
                    }
                    """,
                    )
    class Meta:
        db_table = "patient"

    def __str__(self):
        return f"{self.first_name} {self.last_name}".strip()


class Doctor(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    specialty = models.CharField(
        max_length=50,
        choices=Specialty.choices,
    )
    working_hours = models.JSONField(default=dict, blank=True, help_text='{"mon": [["09:00", "13:00"], ["14:00", "17:00"]], "tue": [["09:00", "17:00"]], ...}')
    avg_consult_minutes = models.IntegerField(default=20)
    buffer_minutes = models.IntegerField(default=10)
    holidays = models.JSONField(
        default=list,
        blank=True,
        help_text='["2026-01-01", "2026-08-15", "2026-12-25"]',
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "doctor"

    def __str__(self):
        return self.name


class Conversation(models.Model):
    CHANNEL_CHOICES = [
        ("web", "Web"),
        ("portal", "Portal"),
        ("app", "App"),
        ("whatsapp", "WhatsApp"),
        ("sms", "SMS"),
        ("voice", "Voice"),
    ]
    id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    channel = models.CharField(
        max_length=20,
        choices=CHANNEL_CHOICES,
        default="sms",
    )
    agent_context = models.JSONField(
        default=dict,
        blank=True,
        help_text='Scratch state passed between agents, e.g. {"intent_stack": ["book_appointment"], "verified": false, "active_agent": "scheduling"}',
    )
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "patient_conversation"

    def __str__(self):
        return f"Conversation {self.id} with {self.patient.first_name} {self.patient.last_name}"

class Message(models.Model):
    id = models.AutoField(primary_key=True)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=[("Patient", "Patient"), ("Assistant", "Assistant"), ("System", "System"), ("Staff", "Staff")])
    content = models.TextField()
    agent_context = models.JSONField(
        default=dict,
        blank=True,
        help_text='Scratch state passed between agents, e.g. {"intent_stack": ["book_appointment"], "verified": false, "active_agent": "scheduling"}',
    )
    class Meta:
        db_table = "patient_message"

    def __str__(self):
        return f"Message {self.id} in Conversation {self.conversation.id} ({self.role})"


class OTPChallenge(models.Model):
    id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    channel = models.CharField(max_length=10, choices=[("SMS", "SMS"), ("email", "email"),("whatsapp", "whatsapp"),])
    code_hash = models.CharField(max_length=128, help_text="SHA-256 hash of the code. Never store the plain code.")
    expires_at = models.DateTimeField(help_text="Expires 10 minutes after the code is generated.")
    attempts = models.PositiveSmallIntegerField(default=0, help_text="Number of verification attempts made.")
    max_attempts = models.PositiveSmallIntegerField(default=5, help_text="Maximum allowed verification attempts.")
    consumed_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the code was successfully used. Null if unused.")

    class Meta:
        db_table = "patient_otpchallenge"
    
    def __str__(self):
        return f"OTPChallenge {self.id} for Patient {self.patient.first_name} {self.patient.last_name} via {self.channel}"


class SentNotification(models.Model):
    id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    channel = models.CharField(max_length=10, choices=[("SMS", "SMS"), ("email", "email"),("whatsapp", "whatsapp"),])
    recipient = models.CharField(max_length=255, help_text="Destination the notification was sent to, e.g. a phone number or email address.")
    rendered_content = models.TextField(help_text="Final message body actually sent to the recipient, after template rendering.")
    status = models.CharField(max_length=10, choices=[("queued", "queued"), ("sent", "sent"),("delivered", "delivered"),("failed","failed")])
    provider_message_id = models.CharField(max_length=100, null=True, blank=True, help_text="Message ID returned by the external notification provider.")

    class Meta:
        db_table = "patient_sentnotification"

    def __str__(self):
        return f"SentNotification {self.id} to Patient {self.patient.first_name} {self.patient.last_name} via {self.channel}"
class AuditEvent(models.Model):
    id = models.AutoField(primary_key=True)
    actor_type = models.CharField(
        max_length=10,
        choices=[
            ("patient", "patient"),
            ("staff", "staff"),
            ("agent", "agent"),
            ("system", "system"),
        ],
    )
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    actor_id = models.CharField(max_length=100, help_text="Identifier of the actor that performed the action, e.g. patient id, staff user id, or agent name.")
    action = models.CharField(max_length=100, help_text="What happened, e.g. 'appointment.booked', 'patient.verified', 'otp.failed'.")
    payload = models.JSONField(default=dict, blank=True, help_text="Extra detail about the event, e.g. old/new values, reason, target object ids.")
    created_at = models.DateTimeField(auto_now_add=True, help_text="When the event occurred. Set once at creation and never changes.")

    class Meta:
        db_table = "patient_auditevent"
    
    def __str__(self):
        return f"AuditEvent {self.id} by {self.actor_type} {self.actor_id} for Patient {self.patient.first_name} {self.patient.last_name}: {self.action}"


class EventLog(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=60, db_index=True, help_text="Event name, e.g. 'registration.completed', 'appointment.booked'.")
    payload = models.JSONField(default=dict, blank=True, help_text="Event data passed to subscribers.")
    processed = models.BooleanField(default=False, help_text="Whether all subscribers have handled this event.")
    error = models.TextField(null=True, blank=True, help_text="Subscriber failure detail, if processing failed. Null on success.")

    class Meta:
        db_table = "event_log"

    def __str__(self):
        return f"EventLog {self.id}: {self.name} (processed={self.processed})"
