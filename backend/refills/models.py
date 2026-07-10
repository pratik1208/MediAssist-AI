"""Refill coordination models (Agent 4, Phase 1) — SCHEMA.md §refills."""

from django.db import models

from core.models import Doctor, Patient


class Pharmacy(models.Model):
    name = models.CharField(max_length=150)
    address = models.JSONField(default=dict, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    fax = models.CharField(max_length=20, blank=True)
    erx_identifier = models.CharField(
        max_length=60, null=True, blank=True,
        help_text="e-prescription network ID.",
    )

    class Meta:
        db_table = "pharmacy"

    def __str__(self):
        return self.name


class Prescription(models.Model):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("discontinued", "Discontinued"),
        ("expired", "Expired"),
        # Replaced by a newer row via refill-approval write-back: without
        # this, both rows stay refillable (double-fill risk).
        ("superseded", "Superseded"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, db_index=True)
    prescriber = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    medication_name = models.CharField(max_length=150)
    dose = models.CharField(max_length=60)
    quantity = models.CharField(max_length=40)
    refills_allowed = models.IntegerField(help_text="Total refills the prescriber authorized (FR-M4).")
    refills_used = models.IntegerField(default=0)
    prescribed_date = models.DateField()
    expiry_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    required_labs = models.JSONField(
        default=list, blank=True,
        help_text='List of {"test": ..., "max_age_days": ...} that must be current before a refill (FR-M3).',
    )
    followup_required = models.BooleanField(default=False)
    is_controlled_substance = models.BooleanField(
        default=False,
        help_text="Controlled substances are NEVER auto-processed — always a human decision (PRD Edge Case 12).",
    )

    class Meta:
        db_table = "prescription"

    def __str__(self):
        return f"{self.medication_name} {self.dose} — {self.patient.first_name} {self.patient.last_name} ({self.status})"


class RefillRequest(models.Model):
    STATUS_CHOICES = [
        ("received", "Received"),
        ("eligibility_check", "Eligibility Check"),
        ("paused", "Paused"),
        ("pending_approval", "Pending Approval"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
        ("visit_required", "Visit Required"),
        ("sent_to_pharmacy", "Sent to Pharmacy"),
        ("ready_for_pickup", "Ready for Pickup"),
    ]

    prescription = models.ForeignKey(Prescription, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    pharmacy = models.ForeignKey(Pharmacy, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="received")
    pause_reason = models.CharField(max_length=200, null=True, blank=True)
    renewal_summary = models.JSONField(
        default=dict, blank=True,
        help_text="Structured physician-facing data (FR-M5).",
    )
    summary_text = models.TextField(blank=True, help_text="AI one-paragraph physician summary.")
    decided_by = models.ForeignKey(Doctor, on_delete=models.SET_NULL, null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    # Not in SCHEMA.md but required by Phase 2: adherence is computed from
    # refill timing history, which needs a request timestamp.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "refill_request"

    def __str__(self):
        return f"Refill of {self.prescription.medication_name} for {self.patient.first_name} {self.patient.last_name} — {self.status}"
