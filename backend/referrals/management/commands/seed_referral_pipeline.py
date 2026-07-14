"""seed_referral_pipeline — the full referral lifecycle, for real.

Referral has no seed at all today, so the referral dashboard/queue is empty
on a fresh clinic. This drives five referrals through real service calls
(create_referral, accept_referral, book_specialist_visit, advance_status,
close_loop) so every stage is represented: one left at "created" for staff
to accept, one "accepted", one "appointment_scheduled" (a real booking
against the one in-network specialist), one "closed" (full loop with a
consultation report), one "stalled". It also confirms the triage-drafted
referral seed_assessments creates for Karthik Iyengar — a physician
accepting a draft that triage flagged, the other creation path.

Requires patients, doctors, and specialists to exist; no-ops with a warning
otherwise. Idempotent: keyed on a marker prefix in `reason` (never rewritten
by any service function, unlike TriageAssessment.summary_text).
"""

import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import Doctor, Patient, Specialty
from referrals.models import Referral, Specialist
from referrals.services import (
    accept_referral,
    advance_status,
    book_specialist_visit,
    close_loop,
    create_referral,
)
from scheduling.services import find_available_slots

MARKER = "[seed_referral_pipeline]"


class Command(BaseCommand):
    help = "Seed referrals across every lifecycle stage via real service calls (idempotent)."

    def handle(self, *args, **options):
        referring_doctor = Doctor.objects.filter(specialty="General Medicine").first()
        if referring_doctor is None:
            self.stdout.write(self.style.WARNING(
                "no General Medicine doctor found — run seed_doctors first"))
            return

        created = skipped = 0

        # -- 1. created, untouched -- for staff to accept ------------------------
        created += self._seed_referral(
            "9820020003", Specialty.DERMATOLOGY,
            "New mole with irregular borders, patient requesting dermatology review.",
            "routine", referring_doctor)

        # -- 2. accepted -----------------------------------------------------------
        referral, was_new = self._get_or_create_referral(
            "9820020005", Specialty.DERMATOLOGY,
            "Persistent eczema flare-up unresponsive to OTC treatment.",
            "routine", referring_doctor)
        if referral and was_new:
            specialist = Specialist.objects.filter(specialty=Specialty.DERMATOLOGY).first()
            if specialist:
                accept_referral(referral, specialist)
            created += 1
        elif referral is None:
            skipped += 1

        # -- 3. appointment_scheduled -- real booking, in-network specialist -----
        referral, was_new = self._get_or_create_referral(
            "9820020002", Specialty.CARDIOLOGY,
            "Occasional palpitations, EKG recommended before further workup.",
            "medium", referring_doctor)
        if referral and was_new:
            specialist = Specialist.objects.filter(
                specialty=Specialty.CARDIOLOGY, internal_doctor__isnull=False).first()
            if specialist:
                accept_referral(referral, specialist)
                # find_available_slots builds naive candidate blocks
                # internally (matches scheduling's own convention) --
                # timezone-aware bounds here would fail the comparison.
                now = datetime.datetime.now()
                slots = find_available_slots(
                    specialist.internal_doctor, now, now + datetime.timedelta(days=14))
                if slots:
                    book_specialist_visit(referral, slots[0])
            created += 1
        elif referral is None:
            skipped += 1

        # -- 4. closed -- full loop with a consultation report --------------------
        referral, was_new = self._get_or_create_referral(
            "9820020007", Specialty.GASTROENTEROLOGY,
            "Recurring post-prandial abdominal pain, GI workup requested.",
            "routine", referring_doctor)
        if referral and was_new:
            specialist = Specialist.objects.filter(specialty=Specialty.GASTROENTEROLOGY).first()
            if specialist:
                accept_referral(referral, specialist)
                # No in-network calendar for this specialist -- advance the
                # generic status graph directly, the realistic majority case
                # (most seeded specialists are out-of-network, per
                # seed_specialists.py).
                advance_status(referral, "appointment_scheduled")
                advance_status(referral, "patient_confirmed")
                advance_status(referral, "visit_completed")
                close_loop(referral, {
                    "diagnosis": "Functional dyspepsia",
                    "treatment_plan": "Dietary modification, trial of PPI for 4 weeks.",
                    "medications": ["Omeprazole 20mg daily"],
                    "followup_recommendations": ["Follow up in 6 weeks if symptoms persist"],
                })
            created += 1
        elif referral is None:
            skipped += 1

        # -- 5. stalled --------------------------------------------------------------
        referral, was_new = self._get_or_create_referral(
            "9820020008", Specialty.ENDOCRINOLOGY,
            "Suspected thyroid nodule on exam, endocrinology referral requested.",
            "routine", referring_doctor)
        if referral and was_new:
            advance_status(referral, "stalled")
            created += 1
        elif referral is None:
            skipped += 1

        # -- 6. confirm the triage-drafted referral (seed_assessments) -----------
        karthik = Patient.objects.filter(contact_number="9820030006").first()
        draft = Referral.objects.filter(
            patient=karthik, status="created", referring_doctor=None).first() if karthik else None
        if draft:
            specialist = Specialist.objects.filter(
                specialty=Specialty.CARDIOLOGY, internal_doctor__isnull=False).first()
            if specialist:
                accept_referral(draft, specialist, doctor=referring_doctor)
                created += 1

        if skipped:
            self.stdout.write(self.style.WARNING(
                f"{skipped} roster patients missing — run seed_patients first"))
        self.stdout.write(self.style.SUCCESS(f"seeded {created} new referral actions"))

    def _get_or_create_referral(self, phone, specialty, reason, urgency, doctor):
        patient = Patient.objects.filter(contact_number=phone).first()
        if patient is None:
            return None, False
        existing = Referral.objects.filter(patient=patient, reason__startswith=MARKER).first()
        if existing:
            return existing, False
        referral = create_referral(doctor, patient, specialty, f"{MARKER} {reason}", urgency)
        return referral, True

    def _seed_referral(self, phone, specialty, reason, urgency, doctor):
        referral, was_new = self._get_or_create_referral(phone, specialty, reason, urgency, doctor)
        return 1 if was_new else 0
