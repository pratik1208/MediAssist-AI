from django.db import models

from core.models import Doctor, Patient

URGENCY_CHOICES = [
    ("emergency", "emergency"),
    ("high", "high"),
    ("medium", "medium"),
    ("low", "low"),
    ("routine", "routine"),
]

# Which agent created the booking (SCHEMA: source).
SOURCE_CHOICES = [
    ("scheduling", "scheduling"),
    ("triage", "triage"),
    ("outreach", "outreach"),
    ("caregaps", "caregaps"),
    ("referrals", "referrals"),
    ("priorauth", "priorauth"),
]


class Appointment(models.Model):
    STATUS_CHOICES = [
        ("booked", "booked"),
        ("confirmed", "confirmed"),
        ("completed", "completed"),
        ("cancelled", "cancelled"),
        ("no_show", "no_show"),
    ]
    id = models.AutoField(primary_key=True)
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    # Field names kept as start_time/end_time (SCHEMA "start/end") because the
    # service layer already standardizes on them.
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason = models.TextField()
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="booked")
    room = models.CharField(max_length=30, null=True, blank=True, help_text="Assigned room, if needed (FR-S4).")
    source = models.CharField(max_length=30, choices=SOURCE_CHOICES, default="scheduling")

    class Meta:
        constraints = [
            # No two appointments share the same doctor + start slot. The full
            # overlap check lives in the service layer inside select_for_update.
            models.UniqueConstraint(fields=["doctor", "start_time"], name="unique_doctor_start"),
        ]
        indexes = [
            models.Index(fields=["doctor", "start_time"]),
        ]
        db_table = "appointment"

    def __str__(self):
        return f"Appointment with Dr. {self.doctor.name} for {self.patient} on {self.start_time}"


class Waitlist(models.Model):
    STATUS_CHOICES = [
        ("waiting", "waiting"),
        ("offered", "offered"),
        ("booked", "booked"),
        ("expired", "expired"),
    ]
    id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    # Nullable — a waitlist entry may be specialty-level, not tied to one doctor.
    doctor = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True)
    specialty = models.CharField(max_length=80)
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES)
    preferred_window = models.JSONField(
        default=dict,
        blank=True,
        help_text='Date range / times of day the patient wants, e.g. {"from": "2026-07-10", "to": "2026-07-14", "times": ["morning"]}',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="waiting")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            # Promotion query: find the next waiting patient for a doctor.
            models.Index(fields=["doctor", "status", "urgency", "created_at"]),
        ]
        db_table = "waitlist"

    def __str__(self):
        return f"Waitlist ({self.status}) for {self.patient} — {self.specialty}"
