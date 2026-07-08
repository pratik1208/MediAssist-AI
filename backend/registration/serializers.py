# Registration-specific serializers (Phase 3): start registration,
# demographics, OTP request/verify, document upload, insurance, status.
# Patient/Conversation/Message serializers live in core.serializers — import
# them from there instead of redefining.
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
