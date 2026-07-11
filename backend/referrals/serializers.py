from rest_framework import serializers

from referrals.models import ConsultationReport, Referral, ReferralPackage, Specialist


class SpecialistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Specialist
        fields = "__all__"


class ReferralSerializer(serializers.ModelSerializer):
    class Meta:
        model = Referral
        fields = "__all__"


class ReferralPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReferralPackage
        fields = "__all__"


class ConsultationReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationReport
        fields = "__all__"
