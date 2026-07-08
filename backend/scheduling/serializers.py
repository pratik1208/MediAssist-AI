from rest_framework import serializers

from scheduling.models import (
    Appointment,
    Waitlist,
)


class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = "__all__"


class WaitlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Waitlist
        fields = "__all__"
