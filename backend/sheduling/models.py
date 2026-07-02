from django.db import models

class Doctor(models.Model):
    name = models.CharField(max_length=100)
    specialization = models.CharField(max_length=100)

    def __str__(self):
        return self.name

class Patient(models.Model):
    name = models.CharField(max_length=100)
    age = models.IntegerField()
    contact_number = models.CharField(max_length=15)

    def __str__(self):
        return self.name

class Appointment(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    appointment_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[('Scheduled', 'Scheduled'), ('Completed', 'Completed'), ('Cancelled', 'Cancelled')])
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    reason_for_visit = models.TextField()

    def __str__(self):
        return f"Appointment with Dr. {self.doctor.name} for {self.patient.name} on {self.appointment_date}"


class Waitlist(models.Model):
    doctor = models.ForeignKey(Doctor, on_delete=models.CASCADE)
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    requested_date = models.DateTimeField()
    status = models.CharField(max_length=20, choices=[('Waiting', 'Waiting'), ('Booked', 'Booked'), ('Expired', 'Expired')])
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f"Waitlist for Dr. {self.doctor.name} for {self.patient.name} on {self.requested_date}"

class Conversation(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=[('Patient', 'Patient'), ('Assistant', 'Assistant')])
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
