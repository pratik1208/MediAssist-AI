from rest_framework import serializers


from sheduling.models import Doctor, Patient, Appointment, Waitlist, Conversation, Message
class DoctorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Doctor
        fields = "__all__"
class PatientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Patient
        fields = "__all__"
class AppointmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appointment
        fields = "__all__"
class WaitlistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Waitlist
        fields = "__all__"
class ConversationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Conversation
        fields = "__all__"
class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = "__all__"
