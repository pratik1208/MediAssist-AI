from django.contrib import admin

from triage.models import ClinicalProtocol, EscalationAlert, TriageAssessment

admin.site.register([ClinicalProtocol, TriageAssessment, EscalationAlert])
