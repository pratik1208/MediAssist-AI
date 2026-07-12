"""Outreach campaign models (Agent 7, Phase 1) — SCHEMA.md §outreach.

FKs follow SCHEMA.md's rule: PROTECT for the clinical ownership reference
(patient — a member's outreach history must never silently vanish),
SET_NULL for links that can legitimately change later (assigned_physician),
CASCADE only for pure child rows (CampaignMember, OutboundMessage,
InboundResponse all die with their parent).
"""

from django.db import models

from core.models import Doctor, Patient, SentNotification


class Campaign(models.Model):
    STATUS_CHOICES = [
        ("draft", "draft"),
        ("running", "running"),
        ("paused", "paused"),
        ("completed", "completed"),
    ]

    name = models.CharField(max_length=150)
    clinical_goal = models.TextField()
    cohort_criteria = models.JSONField(
        default=dict, blank=True,
        help_text="Shared criteria schema (FR-O1; reused by caregaps). Defined "
                  "and validated by outreach.services.build_cohort().",
    )
    channel_plan = models.JSONField(
        default=list, blank=True,
        help_text='Ordered escalation plan, e.g. '
                  '[{"channel": "sms", "wait_days": 0}, {"channel": "email", "wait_days": 3}, '
                  '{"channel": "voice", "wait_days": 7}]',
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    schedule = models.JSONField(default=dict, blank=True, help_text="When/how often waves should dispatch.")
    launched_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "outreach_campaign"

    def __str__(self):
        return f"{self.name} ({self.status})"


class CampaignMember(models.Model):
    STATE_CHOICES = [
        ("identified", "identified"),
        ("contacted", "contacted"),
        ("responded", "responded"),
        ("scheduled", "scheduled"),
        ("completed", "completed"),
        ("snoozed", "snoozed"),
        ("opted_out", "opted_out"),
        ("unreachable", "unreachable"),
    ]

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="members")
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name="outreach_memberships")
    state = models.CharField(max_length=20, choices=STATE_CHOICES, default="identified")
    snooze_until = models.DateField(null=True, blank=True, help_text="Edge Case 14.")
    channel_attempts = models.JSONField(
        default=list, blank=True,
        help_text='[{"channel": "sms", "at": "2026-07-10T09:00:00+00:00", "message_id": 12}, ...]',
    )
    outreach_reason = models.CharField(max_length=200, help_text="FR-O3.")
    assigned_physician = models.ForeignKey(
        Doctor, on_delete=models.SET_NULL, null=True, blank=True, related_name="outreach_memberships",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "outreach_campaign_member"
        constraints = [
            models.UniqueConstraint(fields=["campaign", "patient"], name="unique_campaign_patient"),
        ]
        indexes = [
            models.Index(fields=["campaign", "state"]),
        ]

    def __str__(self):
        return f"{self.patient} in {self.campaign.name} ({self.state})"


class OutboundMessage(models.Model):
    member = models.ForeignKey(CampaignMember, on_delete=models.CASCADE, related_name="outbound_messages")
    notification = models.ForeignKey(
        SentNotification, on_delete=models.CASCADE, related_name="outreach_message",
        help_text="Delivery itself is handled by core.notifications.notify().",
    )
    wave_number = models.IntegerField(help_text="Which escalation step this message belongs to.")

    class Meta:
        db_table = "outreach_outbound_message"

    def __str__(self):
        return f"Wave {self.wave_number} message to member #{self.member_id}"


class InboundResponse(models.Model):
    INTENT_CHOICES = [
        ("book", "book"),
        ("snooze", "snooze"),
        ("opt_out", "opt_out"),
        ("question", "question"),
        ("unclear", "unclear"),
    ]

    member = models.ForeignKey(CampaignMember, on_delete=models.CASCADE, related_name="inbound_responses")
    raw_text = models.TextField()
    classified_intent = models.CharField(max_length=20, choices=INTENT_CHOICES, blank=True)
    snooze_until = models.DateField(null=True, blank=True)
    handled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "outreach_inbound_response"

    def __str__(self):
        return f"Response from member #{self.member_id}: {self.classified_intent or 'unclassified'}"
