"""Care gap closure models (Agent 8, Phase 1) — SCHEMA.md §caregaps.

Rules-over-data agent: ClinicalGuideline rows are the rules (Agent 3's
protocol-as-data pattern), ClinicalEvent rows are the data the scanner reads,
CareGap is a detected rule violation, CarePlan bundles a patient's gaps into
one actionable visit (FR-G4).

FKs follow SCHEMA.md's rule: PROTECT for clinical ownership references
(patient history and the guideline a gap was detected against must never
silently vanish), SET_NULL for links that can legitimately change
(closing_event evidence), CASCADE never — none of these rows are pure
children of each other.
"""

from django.db import models
from django.db.models import Q

from core.models import Patient

RISK_TIER_CHOICES = [
    ("high", "high"),
    ("medium", "medium"),
    ("low", "low"),
]


class ClinicalGuideline(models.Model):
    """One preventive-care rule, e.g. "HbA1c every 6 months for diabetics".

    population_criteria uses the SAME schema as outreach.Campaign.cohort_criteria
    (SCHEMA.md: "shared criteria schema") — the Phase 2 scanner resolves it
    through outreach.services.build_cohort, extending _SUPPORTED_CRITERIA_KEYS
    where guidelines need ClinicalEvent-backed keys (e.g. a diagnosis code).
    """

    CARE_ITEM_TYPE_CHOICES = [
        ("screening", "screening"),
        ("test", "test"),
        ("vaccination", "vaccination"),
        ("visit", "visit"),
        ("followup", "followup"),
    ]

    name = models.CharField(max_length=150)
    population_criteria = models.JSONField(
        default=dict, blank=True,
        help_text="Same schema as Campaign.cohort_criteria — who the rule applies to.",
    )
    care_item_type = models.CharField(max_length=20, choices=CARE_ITEM_TYPE_CHOICES)
    care_item_code = models.CharField(
        max_length=40,
        help_text="Matched against ClinicalEvent.code (LOINC/CPT/CVX-style).",
    )
    frequency_days = models.IntegerField(
        help_text="Max allowed gap in days since the last matching ClinicalEvent.",
    )
    risk_tier = models.CharField(max_length=10, choices=RISK_TIER_CHOICES, help_text="FR-G3.")
    version = models.IntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "caregaps_clinical_guideline"

    def __str__(self):
        return f"{self.name} (v{self.version}, {self.risk_tier})"


class ClinicalEvent(models.Model):
    """What the scanner reads — a patient's clinical history, populated by the
    EHR layer / seed data now, document extraction later (Phase 4)."""

    EVENT_TYPE_CHOICES = [
        ("lab", "lab"),
        ("vaccination", "vaccination"),
        ("visit", "visit"),
        ("procedure", "procedure"),
        ("diagnosis", "diagnosis"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="clinical_events")
    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    code = models.CharField(max_length=40, db_index=True, help_text="LOINC/CPT/CVX-style.")
    value = models.JSONField(default=dict, blank=True, help_text='e.g. {"hba1c": 8.4}')
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "caregaps_clinical_event"
        indexes = [
            # "most recent event of code X for this patient" — the scanner's hot query.
            models.Index(fields=["patient", "code", "-occurred_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} {self.code} for patient #{self.patient_id} @ {self.occurred_at:%Y-%m-%d}"


class CareGap(models.Model):
    """A detected violation of one guideline for one patient (FR-G1/G2)."""

    STATUS_CHOICES = [
        ("open", "open"),
        ("outreach", "outreach"),
        ("scheduled", "scheduled"),
        ("completed", "completed"),
        ("closed", "closed"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="care_gaps")
    guideline = models.ForeignKey(ClinicalGuideline, on_delete=models.PROTECT, related_name="gaps")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="open")
    detected_at = models.DateTimeField(auto_now_add=True)
    due_since = models.DateField(help_text="When the care item became overdue.")
    closed_at = models.DateTimeField(null=True, blank=True)
    closing_event = models.ForeignKey(
        ClinicalEvent, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closed_gaps", help_text="FR-G8 evidence the gap was really met.",
    )

    class Meta:
        db_table = "caregaps_care_gap"
        constraints = [
            # One LIVE gap per patient+guideline — a re-scan refreshes the
            # existing open gap instead of stacking duplicates; only after a
            # gap closes may a new cycle open a fresh one.
            models.UniqueConstraint(
                fields=["patient", "guideline"],
                condition=~Q(status="closed"),
                name="unique_live_gap_per_patient_guideline",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "due_since"]),
        ]

    def __str__(self):
        return f"{self.guideline.name} gap for patient #{self.patient_id} ({self.status})"


class CarePlan(models.Model):
    """A patient's open gaps bundled into one actionable plan (FR-G4) —
    "you're due for A, B and C; we can do all three in one visit"."""

    STATUS_CHOICES = [
        ("draft", "draft"),
        ("sent", "sent"),
        ("accepted", "accepted"),
        ("in_progress", "in_progress"),
        ("completed", "completed"),
        ("recycled", "recycled"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="care_plans")
    gaps = models.ManyToManyField(CareGap, related_name="care_plans", blank=True)
    plan_text = models.TextField(blank=True, help_text="AI patient-facing plan (Phase 4).")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "caregaps_care_plan"

    def __str__(self):
        return f"Care plan for patient #{self.patient_id} ({self.status})"
