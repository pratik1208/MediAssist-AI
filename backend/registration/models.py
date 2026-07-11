from django.db import models
from core.models import Patient
# Create your models here.

class InsurancePolicy(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    policy_number = models.CharField(max_length=100)
    member_id = models.CharField(max_length=100, null=True, blank=True)
    provider_name = models.CharField(max_length=100)
    coverage_details = models.TextField()
    # Nullable: a policy dictated in chat has provider + number but no dates;
    # they arrive later from the card extraction or the insurance endpoint.
    coverage_start = models.DateField(null=True, blank=True)
    coverage_end = models.DateField(null=True, blank=True)
    eligibility_status = models.CharField(max_length=50, choices=[("unknown", "unknown"), ("eligible", "eligible"), ("ineligible", "ineligible")])
    eligibility_checked_at = models.DateTimeField(null=True, blank=True)
    raw_extraction = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "patient_insurancepolicy"

    def __str__(self):
        return f"{self.provider_name} - {self.policy_number} for {self.patient.first_name} {self.patient.last_name}"

class IntakeSummary(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    clinical_profile = models.JSONField(default=dict, blank=True, help_text="Structured clinical profile extracted from the intake form.")
    summary_text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "patient_intakesummary"

    def __str__(self):
        return f"Intake Summary for {self.patient.first_name} {self.patient.last_name} at {self.created_at}"

class UploadedDocument(models.Model):
    EXTRACTION_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("done", "Done"),
        ("failed", "Failed"),
    ]

    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)

    document_type = models.CharField(
        max_length=100,
        choices=[
            ("insurance_card", "insurance_card"),
            ("id_card", "id_card"),
            ("prescription", "prescription"),
            ("lab_report", "lab_report"),
            ("referral_letter", "referral_letter"),
            # A specialist's consultation report coming BACK from a referral
            # (Agent 5 FR-F10) — distinct from referral_letter, which goes
            # the other direction (PCP -> specialist).
            ("consultation_report", "consultation_report"),
            ("other", "other"),
        ],
    )
    file = models.FileField(upload_to='uploaded_documents/')
    extraction_status = models.CharField(
        max_length=20,
        choices=EXTRACTION_STATUS_CHOICES,
        default="pending"
    )
    extracted_data = models.JSONField(null=True, blank=True, help_text="Structured fields read from the document by the AI, e.g. policy number, provider name, test results.")
    uploaded_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        db_table = "patient_documents"

    def __str__(self):
        return f"{self.document_type} for {self.patient.first_name} {self.patient.last_name} uploaded at {self.uploaded_at}"
