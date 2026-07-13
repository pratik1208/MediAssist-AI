from django.contrib import admin
from django.contrib.postgres.search import SearchVector

from frontdesk.models import IntentRoute, KnowledgeArticle, PatientSession, StaffTask


class IntentRouteInline(admin.TabularInline):
    model = IntentRoute
    extra = 0
    fields = ("intent", "target_agent", "status", "created_at")
    readonly_fields = ("created_at",)
    show_change_link = True


@admin.register(PatientSession)
class PatientSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "channel", "patient", "authenticated", "created_at", "route_count")
    list_filter = ("channel", "authenticated")
    raw_id_fields = ("patient", "conversation")
    readonly_fields = ("created_at",)
    inlines = [IntentRouteInline]

    @admin.display(description="routes")
    def route_count(self, obj):
        return obj.routes.count()


@admin.register(IntentRoute)
class IntentRouteAdmin(admin.ModelAdmin):
    list_display = ("session", "intent", "target_agent", "status", "created_at")
    list_filter = ("intent", "status", "target_agent")


@admin.register(KnowledgeArticle)
class KnowledgeArticleAdmin(admin.ModelAdmin):
    """The knowledge base is a real staff-editable surface (clinic hours
    change, insurers get added), so saves here must refresh the search
    vector or the article becomes unfindable."""

    list_display = ("title", "tags", "updated_at")
    search_fields = ("title", "body")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        KnowledgeArticle.objects.filter(id=obj.id).update(
            search_vector=SearchVector("title", weight="A") + SearchVector("body", weight="B"),
        )


@admin.register(StaffTask)
class StaffTaskAdmin(admin.ModelAdmin):
    list_display = ("category", "priority", "status", "patient", "claimed_by", "created_at")
    list_filter = ("status", "priority", "category")
    search_fields = ("summary",)
    raw_id_fields = ("patient", "session")
    readonly_fields = ("created_at",)
