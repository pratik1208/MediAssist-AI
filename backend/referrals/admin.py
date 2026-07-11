from django.contrib import admin

from referrals.models import ConsultationReport, Referral, ReferralPackage, Specialist

admin.site.register([Specialist, Referral, ReferralPackage, ConsultationReport])
