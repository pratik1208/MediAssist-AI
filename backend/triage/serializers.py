from rest_framework import serializers

from triage.models import ClinicalProtocol, EscalationAlert, TriageAssessment


class ClinicalProtocolSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalProtocol
        fields = "__all__"


class TriageAssessmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TriageAssessment
        fields = "__all__"


class EscalationAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = EscalationAlert
        fields = "__all__"
