"""After-hours orchestration models (Agent 9, Phase 1) — SCHEMA.md §frontdesk.

The control tower's four tables: PatientSession is one patient conversation
at the front door (named to avoid clashing with django.contrib.sessions),
IntentRoute is the audit trail of every intent the router dispatched (one
row per intent, so multi-intent messages stay traceable — FR-A2/A8),
KnowledgeArticle is the RAG corpus behind FAQ answers (FR-A5), and
StaffTask is the "human needed" queue (FR-A7).

FK notes: session/task patient links are SET_NULL (a queue entry or session
record outliving a patient link is fine — these are operational rows, not
clinical ownership); IntentRoute dies with its session (pure child);
PatientSession dies with its Conversation (it is that conversation's
front-door state).
"""

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models

from core.models import Conversation, Patient


class PatientSession(models.Model):
    # Same channels as core.Conversation — the session mirrors where the
    # conversation is happening.
    CHANNEL_CHOICES = Conversation.CHANNEL_CHOICES

    patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="frontdesk_sessions",
        help_text="Null until authenticated (FR-A3).",
    )
    conversation = models.OneToOneField(
        Conversation, on_delete=models.CASCADE, related_name="frontdesk_session",
    )
    channel = models.CharField(max_length=20, choices=CHANNEL_CHOICES, default="web")
    channel_identifier = models.CharField(
        max_length=32, blank=True, db_index=True,
        help_text="Raw sender address (phone number) for channel-originated "
                   "sessions with no signed token to correlate by -- SMS/WhatsApp "
                   "replies land here via the Phase 6 channel adapter. Blank for "
                   "web/app sessions opened through /frontdesk/start.",
    )
    authenticated = models.BooleanField(default=False)
    pending_intents = models.JSONField(
        default=list, blank=True,
        help_text="Intents queued behind the auth gate, resumed after step-up (FR-A3).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "frontdesk_patient_session"

    def __str__(self):
        who = f"patient #{self.patient_id}" if self.patient_id else "unauthenticated"
        return f"Session {self.id} ({self.channel}, {who})"


class IntentRoute(models.Model):
    """One row per detected intent — a message like "refill my BP meds and
    book my checkup" produces TWO rows, each individually auditable."""

    INTENT_CHOICES = [
        ("appointment", "appointment"),
        ("refill", "refill"),
        ("referral_status", "referral_status"),
        ("pa_status", "pa_status"),
        ("care_gap", "care_gap"),
        ("symptoms", "symptoms"),
        ("faq", "faq"),
        ("other", "other"),
    ]
    STATUS_CHOICES = [
        ("routed", "routed"),
        ("completed", "completed"),
        ("escalated", "escalated"),
    ]

    session = models.ForeignKey(PatientSession, on_delete=models.CASCADE, related_name="routes")
    intent = models.CharField(max_length=20, choices=INTENT_CHOICES)
    target_agent = models.CharField(max_length=30)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="routed")
    payload = models.JSONField(default=dict, blank=True, help_text="The router's extraction.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "frontdesk_intent_route"
        indexes = [
            models.Index(fields=["session", "status"]),
        ]

    def __str__(self):
        return f"{self.intent} -> {self.target_agent} ({self.status})"


class KnowledgeArticle(models.Model):
    """The RAG corpus (FR-A5): clinic hours, locations, accepted insurance,
    prep instructions, billing FAQs. Postgres full-text IS the retrieval
    layer (search_vector + GIN); embeddings are a later upgrade if quality
    demands it. search_vector is refreshed by whatever writes the article
    (seed command / admin save)."""

    title = models.CharField(max_length=200)
    body = models.TextField()
    tags = models.JSONField(default=list, blank=True, help_text='e.g. ["hours", "locations"]')
    search_vector = SearchVectorField(null=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "frontdesk_knowledge_article"
        indexes = [
            GinIndex(fields=["search_vector"]),
        ]

    def __str__(self):
        return self.title


class StaffTask(models.Model):
    """The "human needed" queue (FR-A7). Kept separate from triage's
    EscalationAlert on purpose: that table is clinical escalation tied to an
    assessment; this one is operational front-door work (insurance disputes,
    unanswerable questions) with its own claim/resolve workflow."""

    CATEGORY_CHOICES = [
        ("mental_health", "mental_health"),
        ("stroke", "stroke"),
        ("insurance_dispute", "insurance_dispute"),
        ("controlled_substance", "controlled_substance"),
        ("unanswered_question", "unanswered_question"),
        ("manual_review", "manual_review"),
    ]
    PRIORITY_CHOICES = [
        ("critical", "critical"),
        ("high", "high"),
        ("normal", "normal"),
    ]
    STATUS_CHOICES = [
        ("open", "open"),
        ("claimed", "claimed"),
        ("resolved", "resolved"),
    ]

    session = models.ForeignKey(
        PatientSession, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="staff_tasks",
    )
    patient = models.ForeignKey(
        Patient, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="frontdesk_tasks",
    )
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="normal")
    summary = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="open")
    claimed_by = models.CharField(max_length=100, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "frontdesk_staff_task"
        indexes = [
            models.Index(fields=["status", "priority"]),
        ]

    def __str__(self):
        return f"[{self.priority}] {self.category} ({self.status})"
