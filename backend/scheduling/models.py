from django.db import models


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


class Doctor(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    specialization = models.CharField(
        max_length=50,
        choices=Specialty.choices,
    )
    working_hours_start = models.TimeField()
    working_hours_end = models.TimeField()

    def __str__(self):
        return self.name


class Patient(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    contact_number = models.CharField(max_length=15)

    def __str__(self):
        return self.name


class Appointment(models.Model):
    id = models.AutoField(primary_key=True)
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    appointment_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[("Scheduled", "Scheduled"), ("Completed", "Completed"), ("Cancelled", "Cancelled")])
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason_for_visit = models.TextField()

    def __str__(self):
        return f"Appointment with Dr. {self.doctor.name} for {self.patient.name} on {self.appointment_date}"


class Waitlist(models.Model):
    id = models.AutoField(primary_key=True)
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    requested_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[("Waiting", "Waiting"), ("Booked", "Booked"), ("Expired", "Expired")])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Waitlist for Dr. {self.doctor.name} for {self.patient.name} on {self.requested_date}"


class Conversation(models.Model):
    id = models.AutoField(primary_key=True)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    id = models.AutoField(primary_key=True)
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=[("Patient", "Patient"), ("Assistant", "Assistant")])
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
