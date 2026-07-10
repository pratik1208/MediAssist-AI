from django.contrib import admin

from refills.models import Pharmacy, Prescription, RefillRequest

admin.site.register([Pharmacy, Prescription, RefillRequest])
