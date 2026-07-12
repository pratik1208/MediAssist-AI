from django.contrib import admin

from outreach.models import Campaign, CampaignMember, InboundResponse, OutboundMessage


class CampaignMemberInline(admin.TabularInline):
    model = CampaignMember
    extra = 0
    fields = ("patient", "state", "outreach_reason", "assigned_physician", "snooze_until")
    raw_id_fields = ("patient", "assigned_physician")
    show_change_link = True


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    """Campaign is a real staff surface until the analytics dashboard exists
    (Phase 5), so this gets proper list/filter/search rather than a bare
    admin.site.register()."""

    list_display = ("name", "status", "launched_at", "created_at", "member_count")
    list_filter = ("status",)
    search_fields = ("name", "clinical_goal")
    readonly_fields = ("created_at",)
    inlines = [CampaignMemberInline]

    @admin.display(description="members")
    def member_count(self, obj):
        return obj.members.count()


@admin.register(CampaignMember)
class CampaignMemberAdmin(admin.ModelAdmin):
    list_display = ("campaign", "patient", "state", "outreach_reason", "assigned_physician", "snooze_until")
    list_filter = ("state", "campaign")
    search_fields = ("patient__first_name", "patient__last_name", "outreach_reason")
    autocomplete_fields = ("campaign",)
    raw_id_fields = ("patient", "assigned_physician")


@admin.register(OutboundMessage)
class OutboundMessageAdmin(admin.ModelAdmin):
    list_display = ("member", "wave_number", "notification")
    list_filter = ("wave_number",)


@admin.register(InboundResponse)
class InboundResponseAdmin(admin.ModelAdmin):
    list_display = ("member", "classified_intent", "handled", "created_at")
    list_filter = ("classified_intent", "handled")
    search_fields = ("raw_text",)
