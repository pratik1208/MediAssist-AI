from rest_framework import serializers

from priorauth.models import (
    AuthorizationPackage,
    AuthorizationRequest,
    PayerMessage,
    PayerRule,
    TreatmentOrder,
)


class PayerRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayerRule
        fields = "__all__"


class TreatmentOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = TreatmentOrder
        fields = "__all__"


class AuthorizationRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorizationRequest
        fields = "__all__"


class AuthorizationPackageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuthorizationPackage
        fields = "__all__"


class PayerMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayerMessage
        fields = "__all__"
