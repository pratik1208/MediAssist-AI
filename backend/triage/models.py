from django.db import models
from core.models import Patient, Conversation


# Create your models here.
class ClinicalProtocol(models.Model):
    name = models.CharField(max_length=100, unique=True)
    symptom_keywords = models.JSONField(default=list, blank=True, help_text="List of keywords associated with the clinical protocol for symptom matching.")
    question_flow = models.JSONField(default=list, blank=True, help_text="Structured representation of the question flow for the clinical protocol.")
    disposition_rules = models.JSONField(
        default=dict, blank=True, help_text="Rules for determining patient disposition based on reported symptoms and findings."
    )
    version = models.CharField(max_length=20, default="1.0", help_text="Version of the clinical protocol.")
    approved_by = models.CharField(max_length=100, null=True, blank=True, help_text="Name of the person or entity that approved the clinical protocol.")
    is_active = models.BooleanField(default=True, help_text="Indicates whether the clinical protocol is currently active and in use.")

    class Meta:
        db_table = "clinical_protocol"

    def __str__(self):
        return self.name


class TriageAssessment(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    # Nullable: an emergency caught by the red-flag screen escalates before
    # any protocol is matched.
    clinical_protocol = models.ForeignKey(ClinicalProtocol, on_delete=models.CASCADE, null=True, blank=True)
    reported_symptoms = models.JSONField(default=dict, blank=True, help_text="Structured data of reported symptoms.")
    findings = models.JSONField(default=dict, blank=True, help_text="Structured data of findings from the assessment.")
    acuity = models.CharField(max_length=50, choices=[("low", "Low"), ("medium", "Medium"), ("high", "High"), ('emergency', 'Emergency'),('minimal', 'Minimal')], help_text="The acuity level of the patient based on the assessment.")
    disposition = models.CharField(
        max_length=50,
        choices=[("ed_now", "Go to Emergency Department Now"), ("same_day", "Same Day"), ("24_48h", "24-48 Hours"), ("routine", "Routine"), ("self_care", "Self-Care")],
        help_text="The recommended disposition for the patient based on the assessment.",
    )
    summary_text = models.TextField(help_text="A concise summary of the assessment, including presenting symptoms and findings.")
    status = models.CharField(max_length=20, choices=[("pending", "Pending"), ("completed", "Completed"), ("reviewed", "Reviewed"), ("escalated", "Escalated")], default="pending")

    class Meta:
        db_table = "triage_assessment"

    def __str__(self):
        return f"Triage Assessment for {self.patient.first_name} {self.patient.last_name} - Status: {self.status}"


class EscalationAlert(models.Model):
    assessment = models.ForeignKey(TriageAssessment, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    source_agent = models.CharField(max_length=100, help_text="The agent (human or AI) that generated the escalation alert.")
    category = models.CharField(
        max_length=20,
        choices=[
            ("emergency", "Emergency"),
            ("mental_health", "Mental Health"),
            ("stroke", "Stroke"),
            ("controlled_substance", "Controlled Substance"),
            ("other", "Other"),
            ("insurance_dispute", "Insurance Dispute"),
        ],
    )
    priority = models.CharField(max_length=20, choices=[("high", "High"), ("medium", "Medium"), ("low", "Low")], help_text="The priority level of the escalation alert.")
    summary = models.TextField(help_text="A brief summary of the reason for the escalation alert.")
    acknowledged_at = models.DateTimeField(null=True, blank=True, help_text="Timestamp when the alert was acknowledged by a human.")
    status = models.CharField(
        max_length=20,
        choices=[("open", "Open"), ("acknowledged", "Acknowledged"), ("resolved", "Resolved")],
        default="open",
        help_text="The current status of the escalation alert.",
    )
    class Meta:
        db_table = "escalation_alert"

    def __str__(self):
        return f"Escalation Alert for {self.patient.first_name} {self.patient.last_name} - Category: {self.category}, Priority: {self.priority}"
