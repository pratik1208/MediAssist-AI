from rest_framework import serializers

from registration.models import InsurancePolicy, IntakeSummary, UploadedDocument


class InsurancePolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = InsurancePolicy
        fields = "__all__"


class IntakeSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = IntakeSummary
        fields = "__all__"


class UploadedDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedDocument
        fields = "__all__"
