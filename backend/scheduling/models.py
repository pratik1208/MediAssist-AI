from django.db import models

from core.models import Doctor, Patient



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


