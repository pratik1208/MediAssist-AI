from django.contrib import admin as django_admin

from scheduling.models import (
    Appointment,
    Waitlist,
)
from core.models import Message, Patient, Doctor, Conversation

# Register your models here.

django_admin.site.register([Doctor, Patient, Appointment, Waitlist, Conversation, Message])


@django_admin.action(description="Cancel and promote waitlist")
def cancel_and_promote(modeladmin, request, queryset):
    """
    Placeholder.
    The waitlist promotion logic will be implemented in services.py
    during Phase 4.
    """
    pass
