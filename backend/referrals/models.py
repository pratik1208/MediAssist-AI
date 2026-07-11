"""Referral execution models (Agent 5, Phase 1) — SCHEMA.md §referrals.

FKs follow SCHEMA.md's rule: PROTECT for the clinical ownership references
(patient, referring_doctor — a referral's history must never silently
vanish), SET_NULL for links that can legitimately change after the fact
(specialist gets re-matched, appointment gets rebooked), CASCADE only for
pure child rows (ReferralPackage, ConsultationReport).
"""

from django.db import models

from core.models import Doctor, Patient, Specialty
from registration.models import UploadedDocument
from scheduling.models import Appointment, URGENCY_CHOICES


class Specialist(models.Model):
    CONTACT_CHANNEL_CHOICES = [
        ("phone", "phone"),
        ("e_referral", "e_referral"),
        ("email", "email"),
        ("api", "api"),
    ]

    name = models.CharField(max_length=150)
    practice_name = models.CharField(max_length=150, blank=True)
    # Reuses core.Specialty (the same enum Doctor uses) so matching against
    # Referral.specialty_needed is an exact comparison, not fuzzy text.
    specialty = models.CharField(max_length=80, choices=Specialty.choices, db_index=True)
    address = models.JSONField(
        default=dict, blank=True,
        help_text='{"line1": ..., "city": ..., "postal_code": ..., "lat": ..., "lng": ...} '
                  "— postal_code (or lat/lng) is what distance ranking uses.",
    )
    accepted_insurances = models.JSONField(
        default=list, blank=True, help_text='["BlueShield", "Star Health", ...]',
    )
    languages = models.JSONField(default=list, blank=True, help_text='["en", "hi", "mr"]')
    accepting_new_patients = models.BooleanField(default=True)
    contact_channel = models.CharField(max_length=20, choices=CONTACT_CHANNEL_CHOICES)
    consultation_fee = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    # In-network specialists reuse the scheduling calendar instead of the
    # simulated outreach channel above.
    internal_doctor = models.OneToOneField(
        Doctor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="specialist_profile",
    )

    class Meta:
        db_table = "referrals_specialist"

    def __str__(self):
        return f"{self.name} ({self.specialty})"


class Referral(models.Model):
    STATUS_CHOICES = [
        ("created", "created"),
        ("accepted", "accepted"),
        ("appointment_scheduled", "appointment_scheduled"),
        ("patient_confirmed", "patient_confirmed"),
        ("visit_completed", "visit_completed"),
        ("report_received", "report_received"),
        ("closed", "closed"),
        ("stalled", "stalled"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="referrals")
    # Nullable: a triage handoff (Phase 6) auto-creates a draft referral with
    # no referring_doctor yet — a physician must confirm it (attach
    # themselves) before it can be accepted by a specialist. A physician's
    # own one-click referral (FR-F1) always sets this at creation.
    referring_doctor = models.ForeignKey(
        Doctor, on_delete=models.PROTECT, related_name="referrals_made",
        null=True, blank=True,
    )
    specialist = models.ForeignKey(
        Specialist, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="referrals", help_text="Nullable until match_specialists() picks one.",
    )
    specialty_needed = models.CharField(max_length=80, choices=Specialty.choices)
    reason = models.TextField()
    urgency = models.CharField(max_length=20, choices=URGENCY_CHOICES)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="created")
    status_history = models.JSONField(
        default=list, blank=True,
        help_text='[{"status": "created", "at": "2026-07-10T09:00:00+00:00"}, ...] '
                  "— appended by services.advance_status(), never edited directly.",
    )
    # Internal bookings go through Agent 1's Appointment; external-office
    # visits (no in-network calendar) only get a plain timestamp.
    appointment = models.ForeignKey(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="referral",
    )
    external_appointment_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "referrals_referral"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"Referral #{self.id}: {self.patient} -> {self.specialty_needed} ({self.status})"


class ReferralPackage(models.Model):
    referral = models.OneToOneField(Referral, on_delete=models.CASCADE, related_name="package")
    selected_chart_data = models.JSONField(
        default=dict, blank=True,
        help_text="Only the specialty-relevant chart items the AI selected (FR-F2).",
    )
    summary_text = models.TextField(blank=True, help_text="AI-written referral summary.")
    attached_documents = models.JSONField(
        default=list, blank=True,
        help_text="List of registration.UploadedDocument ids attached to the package (FR-F4).",
    )

    class Meta:
        db_table = "referrals_package"

    def __str__(self):
        return f"Package for referral #{self.referral_id}"


class ConsultationReport(models.Model):
    referral = models.OneToOneField(Referral, on_delete=models.CASCADE, related_name="report")
    diagnosis = models.TextField(blank=True)
    treatment_plan = models.TextField(blank=True)
    medications = models.JSONField(default=list, blank=True)
    followup_recommendations = models.JSONField(default=list, blank=True)
    source_document = models.ForeignKey(
        UploadedDocument, on_delete=models.SET_NULL, null=True, blank=True,
    )

    class Meta:
        db_table = "referrals_consultation_report"

    def __str__(self):
        return f"Consultation report for referral #{self.referral_id}"


class SpecialistOutreachTask(models.Model):
    """FR-F3 contact log (Phase 4): a queued outbound message to a
    specialist's office. Deliberately simple — a templated-message queue,
    not a real automated call/email sender or voice agent yet (that's a
    later enhancement); this just records what would be sent and lets a
    human or a future sender mark it done."""

    STATUS_CHOICES = [
        ("queued", "queued"),
        ("sent", "sent"),
        ("failed", "failed"),
    ]

    referral = models.ForeignKey(Referral, on_delete=models.CASCADE, related_name="outreach_tasks")
    specialist = models.ForeignKey(Specialist, on_delete=models.CASCADE)
    channel = models.CharField(max_length=20, choices=Specialist.CONTACT_CHANNEL_CHOICES)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "referrals_outreach_task"

    def __str__(self):
        return f"Outreach to {self.specialist.name} for referral #{self.referral_id} ({self.status})"
