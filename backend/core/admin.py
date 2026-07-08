from django.contrib import admin

# Register your models here.
from core.models import Message, Patient, Doctor, Conversation

admin.site.register([Message, Patient, Doctor, Conversation])
