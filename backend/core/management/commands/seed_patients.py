"""seed_patients — a curated EHR patient roster for end-to-end testing.

The whole point is a deliberate COVERAGE MATRIX so the outreach cohort engine
(outreach.services.build_cohort) has patients that fall in and out of every
supported criterion:

  - age spread (age_min / age_max): ~8 patients are 65+, the rest span 40-64
    and 20-39, plus one Feb-29 birthday for the leap-safe cutoff.
  - all ten preferred_language codes appear (weighted en/hi/mr for the Pune
    setting) so preferred_language_in and the AI per-language render_message
    both have variety.
  - communication_preferences variety: a few fully opted out (every channel
    false -> excluded by _FULLY_OPTED_OUT at enrollment), a few partial, the
    rest reachable (empty dict).

Each row also carries a `tags` list that seed_appointments imports to build a
matching clinical history (recent vs overdue vs never-visited completed
visits, and chronic-no-show rows) — so months_since_last_visit_gte and
missed_appointments_gte have real data too. Tags are NOT persisted (Patient
has no such field); they are consumed only by the appointment seed.

Idempotent: keyed on contact_number (each patient's unique natural key),
rerunning updates in place and never duplicates. `dob` is derived from a
stable `age`, so a "72-year-old" stays 72 no matter when you run the seed.
"""

import datetime

from django.core.management.base import BaseCommand

from core.models import Patient

# Fully opted out of every channel -> excluded from outreach enrollment.
OPTED_OUT = {"sms": False, "email": False, "voice": False, "whatsapp": False}

# (first, last, phone, age, lang, area, prefs, tags)
# tags vocabulary (consumed by seed_appointments):
#   recent      -> one completed visit ~2 months ago
#   overdue     -> one completed visit ~14 months ago (months_since_last_visit_gte 12)
#   never       -> no visits at all (also matches "overdue" cohorts: NULL is included)
#   no_show_x1  -> one no_show appointment
#   no_show_x2  -> two no_show appointments (missed_appointments_gte 2)
#   upcoming    -> one future booked appointment
PATIENTS = [
    # --- 65+ : the flu-shot / senior cohort (age_min 65) --------------------
    {"first": "Kamala", "last": "Iyer", "phone": "9820010001", "age": 72,
     "lang": "ta", "area": "Camp", "prefs": {}, "tags": ["overdue"]},
    {"first": "Ramesh", "last": "Deshpande", "phone": "9820010002", "age": 68,
     "lang": "mr", "area": "Kothrud", "prefs": {"sms": True, "email": False},
     "tags": ["recent"]},
    {"first": "Gurpreet", "last": "Singh", "phone": "9820010003", "age": 75,
     "lang": "pa", "area": "Aundh", "prefs": {}, "tags": ["overdue", "no_show_x2"]},
    {"first": "Meena", "last": "Nair", "phone": "9820010004", "age": 66,
     "lang": "ml", "area": "Baner", "prefs": OPTED_OUT, "tags": ["overdue"]},
    {"first": "Harold", "last": "Fernandes", "phone": "9820010005", "age": 81,
     "lang": "en", "area": "Koregaon Park", "prefs": {}, "tags": ["never"]},
    {"first": "Lakshmi", "last": "Rao", "phone": "9820010006", "age": 69,
     "lang": "te", "area": "Viman Nagar", "prefs": {"voice": True, "sms": False},
     "tags": ["overdue", "upcoming"]},
    {"first": "Ashok", "last": "Kulkarni", "phone": "9820010007", "age": 67,
     "lang": "mr", "area": "Deccan", "prefs": {}, "tags": ["recent"]},
    {"first": "Farida", "last": "Khan", "phone": "9820010008", "age": 78,
     "lang": "hi", "area": "Hadapsar", "prefs": {}, "tags": ["overdue", "no_show_x1"]},

    # --- 40-64 : mid-life -------------------------------------------------
    {"first": "Sunita", "last": "Patil", "phone": "9820020001", "age": 54,
     "lang": "mr", "area": "Wakad", "prefs": {}, "tags": ["overdue"]},
    {"first": "Vijay", "last": "Menon", "phone": "9820020002", "age": 61,
     "lang": "ml", "area": "Aundh", "prefs": {"sms": True, "email": True},
     "tags": ["recent", "no_show_x1"]},
    {"first": "Rina", "last": "Shah", "phone": "9820020003", "age": 47,
     "lang": "gu", "area": "Camp", "prefs": OPTED_OUT, "tags": ["overdue"]},
    {"first": "Anil", "last": "Verma", "phone": "9820020004", "age": 58,
     "lang": "hi", "area": "Shivajinagar", "prefs": {}, "tags": ["no_show_x2"]},
    {"first": "Grace", "last": "D'Souza", "phone": "9820020005", "age": 43,
     "lang": "en", "area": "Kalyani Nagar", "prefs": {"email": True, "sms": False},
     "tags": ["recent"]},
    {"first": "Subhash", "last": "Ghosh", "phone": "9820020006", "age": 63,
     "lang": "bn", "area": "Baner", "prefs": {}, "tags": ["overdue", "upcoming"]},
    {"first": "Prakash", "last": "Naidu", "phone": "9820020007", "age": 51,
     "lang": "te", "area": "Hinjewadi", "prefs": {}, "tags": ["never"]},
    {"first": "Nasreen", "last": "Sheikh", "phone": "9820020008", "age": 49,
     "lang": "hi", "area": "Kondhwa", "prefs": {}, "tags": ["overdue", "no_show_x2"]},
    {"first": "Deepa", "last": "Gowda", "phone": "9820020009", "age": 56,
     "lang": "kn", "area": "Wagholi", "prefs": {}, "tags": ["recent"]},
    {"first": "Thomas", "last": "Mathew", "phone": "9820020010", "age": 60,
     "lang": "ml", "area": "Viman Nagar", "prefs": {}, "tags": ["overdue"]},

    # --- 20-39 : younger --------------------------------------------------
    {"first": "Priyanka", "last": "Joshi", "phone": "9820030001", "age": 29,
     "lang": "mr", "area": "Kothrud", "prefs": {}, "tags": ["recent"]},
    {"first": "Aditya", "last": "Chatterjee", "phone": "9820030002", "age": 34,
     "lang": "bn", "area": "Aundh", "prefs": {"whatsapp": True}, "tags": ["never"]},
    {"first": "Sneha", "last": "Reddy", "phone": "9820030003", "age": 26,
     "lang": "te", "area": "Hinjewadi", "prefs": {}, "tags": ["no_show_x1"]},
    {"first": "Rahul", "last": "Sharma", "phone": "9876543210", "age": 36,
     "lang": "hi", "area": "Shivajinagar", "prefs": {}, "tags": ["recent"]},
    {"first": "Ayesha", "last": "Ansari", "phone": "9820030005", "age": 31,
     "lang": "hi", "area": "Kondhwa", "prefs": OPTED_OUT, "tags": ["recent"]},
    {"first": "Karthik", "last": "Iyengar", "phone": "9820030006", "age": 38,
     "lang": "ta", "area": "Magarpatta", "prefs": {"sms": True}, "tags": ["overdue"]},
    {"first": "Neha", "last": "Kulkarni", "phone": "9820030007", "age": 24,
     "lang": "mr", "area": "Warje", "prefs": {}, "tags": ["never"]},
    {"first": "Rohit", "last": "Mehta", "phone": "9820030008", "age": 33,
     "lang": "gu", "area": "Baner", "prefs": {}, "tags": ["recent", "no_show_x1"]},
    {"first": "Emily", "last": "Pereira", "phone": "9820030009", "age": 28,
     "lang": "en", "area": "Kalyani Nagar", "prefs": {}, "tags": ["upcoming"]},
    {"first": "Sandeep", "last": "Bhat", "phone": "9820030010", "age": 39,
     "lang": "kn", "area": "Wakad", "prefs": {"email": False}, "tags": ["overdue"]},
    {"first": "Manpreet", "last": "Kaur", "phone": "9820030011", "age": 22,
     "lang": "pa", "area": "Vishrantwadi", "prefs": {}, "tags": ["never"]},
    # Feb-29 birthday: exercises build_cohort's leap-safe age cutoff.
    {"first": "Leap", "last": "Fernandez", "phone": "9820030012",
     "dob": datetime.date(1996, 2, 29), "lang": "en", "area": "Camp",
     "prefs": {}, "tags": ["recent"]},
]


def _dob_for(entry, today):
    if "dob" in entry:
        return entry["dob"]
    age = entry["age"]
    # Deterministic, varied month/day (all <= 28, so always valid), stable
    # across reruns. Anchored on age so the patient stays that age over time.
    idx = int(entry["phone"][-3:])
    month = (idx * 37) % 12 + 1
    day = (idx * 17) % 28 + 1
    return datetime.date(today.year - age, month, day)


class Command(BaseCommand):
    help = "Seed ~30 curated patients with a cohort-coverage matrix (idempotent)."

    def handle(self, *args, **options):
        today = datetime.date.today()
        created = updated = 0
        for entry in PATIENTS:
            defaults = {
                "first_name": entry["first"],
                "last_name": entry["last"],
                "dob": _dob_for(entry, today),
                "email": f"{entry['first'].lower()}.{entry['last'].lower().replace(chr(39), '')}@example.com",
                "preferred_language": entry["lang"],
                "communication_preferences": entry["prefs"],
                "address": {"line1": f"{int(entry['phone'][-3:])} {entry['area']} Rd",
                            "city": "Pune", "state": "MH", "zip": "411000"},
                "registration_status": "complete",
                "identity_verified": True,
            }
            _, was_created = Patient.objects.update_or_create(
                contact_number=entry["phone"], defaults=defaults,
            )
            created += was_created
            updated += not was_created

        self.stdout.write(self.style.SUCCESS(
            f"seeded {len(PATIENTS)} patients ({created} created, {updated} updated)"
        ))
