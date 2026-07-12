from django.contrib import admin

from priorauth.models import (
    AuthorizationPackage,
    AuthorizationRequest,
    PayerMessage,
    PayerRule,
    TreatmentOrder,
)

admin.site.register([PayerRule, TreatmentOrder, AuthorizationRequest,
                     AuthorizationPackage, PayerMessage])
