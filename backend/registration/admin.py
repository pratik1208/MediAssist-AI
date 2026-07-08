from django.contrib import admin

# Register your models here.
from registration.models import InsurancePolicy, IntakeSummary, UploadedDocument

admin.site.register([InsurancePolicy, IntakeSummary, UploadedDocument])
