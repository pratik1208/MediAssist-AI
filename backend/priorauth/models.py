"""Prior authorization models (Agent 6, Phase 1) — SCHEMA.md §priorauth.

FKs follow the same rule referrals already established (SCHEMA.md's own
stated rule, line 10): PROTECT for clinical/financial ownership references
that must never silently vanish (patient, policy), SET_NULL for links that
can legitimately change or be edited later (matched_rule, referral), CASCADE
only for pure child rows (AuthorizationPackage, PayerMessage, and
AuthorizationRequest itself — it's created immediately alongside its order
and has no independent life apart from it).
"""

from django.db import models

from core.models import Doctor, Patient
from referrals.models import Referral
from registration.models import InsurancePolicy


class PayerRule(models.Model):
    NETWORK_CHOICES = [
        ("in_network", "in_network"),
        ("any", "any"),
    ]
    SUBMISSION_CHANNEL_CHOICES = [
        ("api", "api"),
        ("epa", "epa"),
        ("portal", "portal"),
        ("fax", "fax"),
    ]

    payer_name = models.CharField(max_length=120)
    # Nullable: a payer-wide rule (no specific plan) applies to every plan
    # under that payer — matching treats a blank plan as "any".
    plan = models.CharField(max_length=120, null=True, blank=True)
    cpt_pattern = models.CharField(max_length=60, null=True, blank=True,
                                   help_text="glob/regex against TreatmentOrder.cpt_code")
    icd10_pattern = models.CharField(max_length=60, null=True, blank=True,
                                     help_text="glob/regex against TreatmentOrder.icd10_code")
    medication_pattern = models.CharField(max_length=60, null=True, blank=True,
                                          help_text="glob/regex against TreatmentOrder.medication")
    network_requirement = models.CharField(max_length=20, choices=NETWORK_CHOICES,
                                           null=True, blank=True)
    requires_auth = models.BooleanField()
    submission_channel = models.CharField(max_length=20, choices=SUBMISSION_CHANNEL_CHOICES)
    required_documentation = models.JSONField(
        default=list, blank=True,
        help_text='List of evidence categories (FR-P2), e.g. '
                  '["diagnosis", "physician_notes", "imaging_reports"].',
    )

    class Meta:
        db_table = "priorauth_payer_rule"

    def __str__(self):
        return f"{self.payer_name} ({self.plan or 'any plan'})"


class TreatmentOrder(models.Model):
    ORDER_TYPE_CHOICES = [
        ("medication", "medication"),
        ("imaging", "imaging"),
        ("procedure", "procedure"),
        ("device", "device"),
        ("therapy", "therapy"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="treatment_orders")
    # Nullable: FR-T7 (Phase 6) lets a triage disposition trigger detection
    # directly, the same way a triage handoff creates a draft Referral with
    # no referring_doctor yet — an ordering physician confirms it later.
    ordering_doctor = models.ForeignKey(
        Doctor, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="treatment_orders_placed",
    )
    order_type = models.CharField(max_length=20, choices=ORDER_TYPE_CHOICES)
    cpt_code = models.CharField(max_length=10, null=True, blank=True)
    icd10_code = models.CharField(max_length=10, null=True, blank=True)
    medication = models.CharField(max_length=150, null=True, blank=True)
    referral = models.ForeignKey(
        Referral, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="treatment_orders",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "priorauth_treatment_order"

    def __str__(self):
        what = self.medication or self.cpt_code or self.order_type
        return f"{self.order_type} order ({what}) for {self.patient}"


class AuthorizationRequest(models.Model):
    STATUS_CHOICES = [
        ("detected", "detected"),
        ("gathering_evidence", "gathering_evidence"),
        ("ready_for_review", "ready_for_review"),
        ("submitted", "submitted"),
        ("under_review", "under_review"),
        ("info_requested", "info_requested"),
        ("approved", "approved"),
        ("denied", "denied"),
    ]

    order = models.OneToOneField(TreatmentOrder, on_delete=models.CASCADE, related_name="authorization")
    policy = models.ForeignKey(InsurancePolicy, on_delete=models.PROTECT, related_name="authorization_requests")
    matched_rule = models.ForeignKey(
        PayerRule, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="authorization_requests",
        help_text="Nullable — rules can be edited/retired without deleting past requests.",
    )
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="detected")
    status_history = models.JSONField(
        default=list, blank=True,
        help_text='[{"status": "detected", "at": "..."}, ...] — appended by '
                  "services.advance_status(), never edited directly.",
    )
    denial_reason = models.TextField(null=True, blank=True)
    appeal_suggested = models.BooleanField(default=False, help_text="FR-P7")
    external_reference = models.CharField(max_length=80, null=True, blank=True,
                                          help_text="The payer's own case number, once submitted.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "priorauth_authorization_request"
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"AuthorizationRequest #{self.id} for order #{self.order_id} ({self.status})"


class AuthorizationPackage(models.Model):
    request = models.OneToOneField(AuthorizationRequest, on_delete=models.CASCADE, related_name="package")
    demographics_snapshot = models.JSONField(default=dict, blank=True)
    codes = models.JSONField(default=dict, blank=True, help_text="CPT/ICD-10 codes on the order.")
    evidence = models.JSONField(default=dict, blank=True, help_text="Gathered items by category (FR-P2).")
    reviewer_summary = models.TextField(blank=True, help_text="AI medical-necessity summary (FR-P3).")

    class Meta:
        db_table = "priorauth_authorization_package"

    def __str__(self):
        return f"Package for request #{self.request_id}"


class PayerMessage(models.Model):
    DIRECTION_CHOICES = [
        ("outbound", "outbound"),
        ("inbound", "inbound"),
    ]

    request = models.ForeignKey(AuthorizationRequest, on_delete=models.CASCADE, related_name="messages")
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    content = models.TextField(help_text="Full audit trail of everything exchanged (FR-P6).")
    parsed = models.JSONField(default=dict, blank=True, help_text="AI structured interpretation (Phase 4).")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "priorauth_payer_message"
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.direction} message on request #{self.request_id}"
