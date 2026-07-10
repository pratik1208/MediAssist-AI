from rest_framework import serializers

from refills.models import Pharmacy, Prescription, RefillRequest


class PharmacySerializer(serializers.ModelSerializer):
    class Meta:
        model = Pharmacy
        fields = "__all__"


class PrescriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prescription
        fields = "__all__"


class RefillRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = RefillRequest
        fields = "__all__"
