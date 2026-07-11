"""seed_specialists — load starter Specialist rows (Agent 5, Phase 1).

Spans multiple specialties, insurances, and locations so match_specialists()
(Phase 2) has real filtering/ranking to do: some accept a given insurance and
some don't, some are full, some are across town. Idempotent — matches on
name, like the other seed commands.
"""

from django.core.management.base import BaseCommand

from core.models import Specialty
from referrals.models import Specialist

INSURANCES = ["BlueShield", "Star Health", "Apollo Munich", "HDFC Ergo"]

SPECIALISTS = [
    {"name": "Dr. Rohan Kulkarni", "practice_name": "Pune Heart Institute",
     "specialty": Specialty.CARDIOLOGY,
     "address": {"city": "Pune", "area": "Shivajinagar", "postal_code": "411005"},
     "accepted_insurances": ["BlueShield", "Star Health"],
     "languages": ["en", "hi", "mr"], "accepting_new_patients": True,
     "contact_channel": "e_referral", "consultation_fee": "1200.00"},
    {"name": "Dr. Neha Kapoor", "practice_name": "CardioCare Clinic",
     "specialty": Specialty.CARDIOLOGY,
     "address": {"city": "Pune", "area": "Kothrud", "postal_code": "411038"},
     "accepted_insurances": ["Apollo Munich"],
     "languages": ["en", "hi"], "accepting_new_patients": False,
     "contact_channel": "phone", "consultation_fee": "1500.00"},
    {"name": "Dr. Sameer Joshi", "practice_name": "SkinFirst Dermatology",
     "specialty": Specialty.DERMATOLOGY,
     "address": {"city": "Pune", "area": "Baner", "postal_code": "411045"},
     "accepted_insurances": ["BlueShield", "HDFC Ergo"],
     "languages": ["en", "mr"], "accepting_new_patients": True,
     "contact_channel": "email", "consultation_fee": "800.00"},
    {"name": "Dr. Ananya Reddy", "practice_name": "Bright Smiles Ortho & Bones",
     "specialty": Specialty.ORTHOPEDICS,
     "address": {"city": "Pune", "area": "Viman Nagar", "postal_code": "411014"},
     "accepted_insurances": ["Star Health", "HDFC Ergo"],
     "languages": ["en", "hi", "te"], "accepting_new_patients": True,
     "contact_channel": "e_referral", "consultation_fee": "1000.00"},
    {"name": "Dr. Imran Sheikh", "practice_name": "Pune Bone & Joint Center",
     "specialty": Specialty.ORTHOPEDICS,
     "address": {"city": "Pune", "area": "Hadapsar", "postal_code": "411028"},
     "accepted_insurances": ["BlueShield"],
     "languages": ["en", "hi", "ur"], "accepting_new_patients": True,
     "contact_channel": "api", "consultation_fee": "950.00"},
    {"name": "Dr. Priya Menon", "practice_name": "NeuroWell Clinic",
     "specialty": Specialty.NEUROLOGY,
     "address": {"city": "Pune", "area": "Aundh", "postal_code": "411007"},
     "accepted_insurances": ["Star Health", "Apollo Munich"],
     "languages": ["en", "ml", "hi"], "accepting_new_patients": True,
     "contact_channel": "e_referral", "consultation_fee": "1800.00"},
    {"name": "Dr. Kavita Rao", "practice_name": "Women's Wellness Center",
     "specialty": Specialty.GYNECOLOGY,
     "address": {"city": "Pune", "area": "Camp", "postal_code": "411001"},
     "accepted_insurances": ["BlueShield", "Star Health", "HDFC Ergo"],
     "languages": ["en", "hi", "mr"], "accepting_new_patients": True,
     "contact_channel": "phone", "consultation_fee": "1100.00"},
    {"name": "Dr. Vikram Desai", "practice_name": "GutHealth Gastroenterology",
     "specialty": Specialty.GASTROENTEROLOGY,
     "address": {"city": "Pune", "area": "Deccan", "postal_code": "411004"},
     "accepted_insurances": ["Apollo Munich", "HDFC Ergo"],
     "languages": ["en", "hi", "gu"], "accepting_new_patients": True,
     "contact_channel": "email", "consultation_fee": "1300.00"},
    {"name": "Dr. Farah Ahmed", "practice_name": "Mindful Psychiatry Practice",
     "specialty": Specialty.PSYCHIATRY,
     "address": {"city": "Pune", "area": "Koregaon Park", "postal_code": "411001"},
     "accepted_insurances": ["BlueShield"],
     "languages": ["en", "hi", "ur"], "accepting_new_patients": True,
     "contact_channel": "e_referral", "consultation_fee": "1600.00"},
    {"name": "Dr. Arjun Nair", "practice_name": "ClearVision Eye Institute",
     "specialty": Specialty.OPHTHALMOLOGY,
     "address": {"city": "Pune", "area": "Wakad", "postal_code": "411057"},
     "accepted_insurances": ["Star Health", "BlueShield"],
     "languages": ["en", "hi", "ml"], "accepting_new_patients": True,
     "contact_channel": "phone", "consultation_fee": "900.00"},
]


class Command(BaseCommand):
    help = "Seed the database with sample referral specialists (idempotent)."

    def handle(self, *args, **kwargs):
        for spec in SPECIALISTS:
            specialist, created = Specialist.objects.update_or_create(
                name=spec["name"], defaults={k: v for k, v in spec.items() if k != "name"},
            )
            self.stdout.write(
                f"{'created' if created else 'updated'}: {specialist.name} "
                f"({specialist.specialty}, accepting={specialist.accepting_new_patients})"
            )
        self.stdout.write(self.style.SUCCESS(f"seeded {len(SPECIALISTS)} specialists"))
