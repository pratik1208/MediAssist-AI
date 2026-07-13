from django.contrib import admin

from caregaps.models import CareGap, CarePlan, ClinicalEvent, ClinicalGuideline


@admin.register(ClinicalGuideline)
class ClinicalGuidelineAdmin(admin.ModelAdmin):
    """Guidelines are the agent's rulebook and stay staff-editable data
    (Agent 3's protocol-as-data pattern), so the admin is a real surface:
    toggle is_active, tweak frequency_days, bump version."""

    list_display = ("name", "care_item_type", "care_item_code",
                    "frequency_days", "risk_tier", "version", "is_active", "gap_count")
    list_filter = ("care_item_type", "risk_tier", "is_active")
    search_fields = ("name", "care_item_code")

    @admin.display(description="gaps")
    def gap_count(self, obj):
        return obj.gaps.count()


@admin.register(ClinicalEvent)
class ClinicalEventAdmin(admin.ModelAdmin):
    list_display = ("patient", "event_type", "code", "occurred_at")
    list_filter = ("event_type",)
    search_fields = ("code", "patient__first_name", "patient__last_name")
    raw_id_fields = ("patient",)


@admin.register(CareGap)
class CareGapAdmin(admin.ModelAdmin):
    list_display = ("guideline", "patient", "status", "due_since", "detected_at", "closed_at")
    list_filter = ("status", "guideline__risk_tier", "guideline")
    search_fields = ("patient__first_name", "patient__last_name", "guideline__name")
    raw_id_fields = ("patient", "closing_event")
    readonly_fields = ("detected_at",)


@admin.register(CarePlan)
class CarePlanAdmin(admin.ModelAdmin):
    list_display = ("patient", "status", "gap_count", "created_at")
    list_filter = ("status",)
    search_fields = ("patient__first_name", "patient__last_name", "plan_text")
    raw_id_fields = ("patient",)
    filter_horizontal = ("gaps",)
    readonly_fields = ("created_at",)

    @admin.display(description="gaps")
    def gap_count(self, obj):
        return obj.gaps.count()
