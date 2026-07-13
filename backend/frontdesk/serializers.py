from rest_framework import serializers

from frontdesk.models import KnowledgeArticle, StaffTask


class KnowledgeArticleSerializer(serializers.ModelSerializer):
    class Meta:
        model = KnowledgeArticle
        # search_vector is a derived column (refreshed by whatever writes the
        # article), never client-supplied.
        exclude = ["search_vector"]


class StaffTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = StaffTask
        fields = "__all__"
