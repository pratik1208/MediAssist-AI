from rest_framework import serializers

from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline


class ClinicalGuidelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalGuideline
        fields = "__all__"


class ClinicalEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalEvent
        fields = "__all__"


class CareGapSerializer(serializers.ModelSerializer):
    class Meta:
        model = CareGap
        fields = "__all__"


class CarePlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = CarePlan
        fields = "__all__"
