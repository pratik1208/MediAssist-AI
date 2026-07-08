from django.contrib import admin as django_admin

from scheduling.models import (
    Appointment,
    Waitlist,
)
# Register your models here.
# Patient, Doctor, Conversation, Message are registered in core/admin.py

django_admin.site.register([Appointment, Waitlist])


@django_admin.action(description="Cancel and promote waitlist")
def cancel_and_promote(modeladmin, request, queryset):
    """
    Placeholder.
    The waitlist promotion logic will be implemented in services.py
    during Phase 4.
    """
    pass
