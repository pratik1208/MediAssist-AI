from rest_framework import serializers

from outreach.models import Campaign, CampaignMember, InboundResponse, OutboundMessage


class CampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = "__all__"


class CampaignMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = CampaignMember
        fields = "__all__"


class OutboundMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = OutboundMessage
        fields = "__all__"


class InboundResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = InboundResponse
        fields = "__all__"
