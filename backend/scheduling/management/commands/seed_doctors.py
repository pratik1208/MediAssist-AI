from django.core.management.base import BaseCommand

from core.models import Doctor, Specialty

# Weekday-only schedule (9–5 with a lunch break).
WEEKDAYS_9_TO_5 = {
    "mon": [["09:00", "13:00"], ["14:00", "17:00"]],
    "tue": [["09:00", "13:00"], ["14:00", "17:00"]],
    "wed": [["09:00", "13:00"], ["14:00", "17:00"]],
    "thu": [["09:00", "13:00"], ["14:00", "17:00"]],
    "fri": [["09:00", "13:00"], ["14:00", "17:00"]],
}

# Full-week schedule so the demo UI always has bookable slots,
# including weekends and evenings.
ALL_WEEK_8_TO_20 = {
    day: [["08:00", "13:00"], ["14:00", "20:00"]]
    for day in ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
}

WEEKENDS_AND_EVENINGS = {
    "mon": [["17:00", "20:00"]],
    "tue": [["17:00", "20:00"]],
    "wed": [["17:00", "20:00"]],
    "thu": [["17:00", "20:00"]],
    "fri": [["17:00", "20:00"]],
    "sat": [["09:00", "17:00"]],
    "sun": [["09:00", "13:00"]],
}


class Command(BaseCommand):
    help = "Seed the database with sample doctors (idempotent)."

    def handle(self, *args, **kwargs):
        doctors = [
            # Two General Medicine doctors with complementary hours — the
            # chat routes most symptoms here, so cover the whole week.
            {"name": "Dr. Asha Mehta", "specialty": Specialty.GENERAL_MEDICINE,
             "working_hours": ALL_WEEK_8_TO_20},
            {"name": "Dr. Jennifer White", "specialty": Specialty.GENERAL_MEDICINE,
             "working_hours": WEEKENDS_AND_EVENINGS},
            {"name": "Dr. John Smith", "specialty": Specialty.CARDIOLOGY,
             "working_hours": ALL_WEEK_8_TO_20},
            {"name": "Dr. Sarah Johnson", "specialty": Specialty.DERMATOLOGY,
             "working_hours": ALL_WEEK_8_TO_20},
            {"name": "Dr. Michael Brown", "specialty": Specialty.PEDIATRICS,
             "working_hours": ALL_WEEK_8_TO_20},
            {"name": "Dr. Emily Davis", "specialty": Specialty.NEUROLOGY,
             "working_hours": WEEKDAYS_9_TO_5},
            {"name": "Dr. David Wilson", "specialty": Specialty.ORTHOPEDICS,
             "working_hours": WEEKDAYS_9_TO_5},
            {"name": "Dr. Lisa Taylor", "specialty": Specialty.GYNECOLOGY,
             "working_hours": WEEKDAYS_9_TO_5},
            {"name": "Dr. James Moore", "specialty": Specialty.ENT,
             "working_hours": WEEKDAYS_9_TO_5},
            {"name": "Dr. Robert Anderson", "specialty": Specialty.PSYCHIATRY,
             "working_hours": WEEKENDS_AND_EVENINGS},
            {"name": "Dr. Maria Garcia", "specialty": Specialty.GASTROENTEROLOGY,
             "working_hours": WEEKDAYS_9_TO_5},
            {"name": "Dr. Vikram Rao", "specialty": Specialty.PULMONOLOGY,
             "working_hours": WEEKDAYS_9_TO_5},
        ]

        # A second, larger wave: every specialty gets at least two doctors,
        # with extra cover where the chat routes most traffic (General
        # Medicine, Pediatrics). Hours rotate through the three schedule
        # shapes so slot variety shows up in the booking UI.
        schedules = [ALL_WEEK_8_TO_20, WEEKDAYS_9_TO_5, WEEKENDS_AND_EVENINGS]
        extra = [
            ("Dr. Ananya Iyer", Specialty.GENERAL_MEDICINE),
            ("Dr. Rohan Kulkarni", Specialty.GENERAL_MEDICINE),
            ("Dr. Priya Nair", Specialty.GENERAL_MEDICINE),
            ("Dr. Thomas Clark", Specialty.GENERAL_MEDICINE),
            ("Dr. Sneha Deshpande", Specialty.CARDIOLOGY),
            ("Dr. Arjun Menon", Specialty.CARDIOLOGY),
            ("Dr. Rachel Lewis", Specialty.CARDIOLOGY),
            ("Dr. Kavita Joshi", Specialty.DERMATOLOGY),
            ("Dr. Nikhil Bhat", Specialty.DERMATOLOGY),
            ("Dr. Laura Hall", Specialty.DERMATOLOGY),
            ("Dr. Meenakshi Pillai", Specialty.PEDIATRICS),
            ("Dr. Sameer Kapoor", Specialty.PEDIATRICS),
            ("Dr. Angela Young", Specialty.PEDIATRICS),
            ("Dr. Rajesh Khanna", Specialty.ORTHOPEDICS),
            ("Dr. Pooja Hegde", Specialty.ORTHOPEDICS),
            ("Dr. Steven Allen", Specialty.ORTHOPEDICS),
            ("Dr. Nandini Reddy", Specialty.GYNECOLOGY),
            ("Dr. Farah Sheikh", Specialty.GYNECOLOGY),
            ("Dr. Karen Scott", Specialty.GYNECOLOGY),
            ("Dr. Aditya Verma", Specialty.NEUROLOGY),
            ("Dr. Shalini Gupta", Specialty.NEUROLOGY),
            ("Dr. Imran Qureshi", Specialty.PSYCHIATRY),
            ("Dr. Deepa Krishnan", Specialty.PSYCHIATRY),
            ("Dr. Suresh Patil", Specialty.OPHTHALMOLOGY),
            ("Dr. Ritu Malhotra", Specialty.OPHTHALMOLOGY),
            ("Dr. Brian Adams", Specialty.OPHTHALMOLOGY),
            ("Dr. Ganesh Shenoy", Specialty.ENT),
            ("Dr. Alka Saxena", Specialty.ENT),
            ("Dr. Manoj Tiwari", Specialty.GASTROENTEROLOGY),
            ("Dr. Sunita Rane", Specialty.GASTROENTEROLOGY),
            ("Dr. Kiran Desai", Specialty.ENDOCRINOLOGY),
            ("Dr. Leela Chandran", Specialty.ENDOCRINOLOGY),
            ("Dr. Peter Walker", Specialty.ENDOCRINOLOGY),
            ("Dr. Abhay Chavan", Specialty.PULMONOLOGY),
            ("Dr. Nisha Fernandes", Specialty.PULMONOLOGY),
            ("Dr. Harish Naik", Specialty.UROLOGY),
            ("Dr. Vandana Kelkar", Specialty.UROLOGY),
            ("Dr. Mohan Swamy", Specialty.ONCOLOGY),
            ("Dr. Grace Turner", Specialty.ONCOLOGY),
            ("Dr. Sanjay Mishra", Specialty.ONCOLOGY),
            ("Dr. Rekha Prasad", Specialty.NEPHROLOGY),
            ("Dr. Anil Kamat", Specialty.NEPHROLOGY),
            ("Dr. Shweta Dixit", Specialty.RHEUMATOLOGY),
            ("Dr. Daniel King", Specialty.RHEUMATOLOGY),
            ("Dr. Usha Menon", Specialty.INFECTIOUS_DISEASE),
            ("Dr. Prakash Jha", Specialty.INFECTIOUS_DISEASE),
            ("Dr. Tanvi Shah", Specialty.ALLERGY_IMMUNOLOGY),
            ("Dr. Olivia Baker", Specialty.ALLERGY_IMMUNOLOGY),
            ("Dr. Ravi Shankar", Specialty.EMERGENCY_MEDICINE),
            ("Dr. Monica Green", Specialty.EMERGENCY_MEDICINE),
        ]
        doctors += [
            {"name": name, "specialty": specialty,
             "working_hours": schedules[i % len(schedules)]}
            for i, (name, specialty) in enumerate(extra)
        ]

        created_count = 0
        updated_count = 0

        for doctor in doctors:
            obj, created = Doctor.objects.get_or_create(
                name=doctor["name"],
                defaults={
                    "specialty": doctor["specialty"],
                    "working_hours": doctor["working_hours"],
                },
            )
            if created:
                created_count += 1
            elif not obj.working_hours:
                # Existing rows from the old seed shape have no schedule —
                # give them one so they can actually offer slots.
                obj.working_hours = doctor["working_hours"]
                obj.save(update_fields=["working_hours"])
                updated_count += 1

        self.stdout.write(self.style.SUCCESS(
            f"{created_count} doctor(s) created, "
            f"{updated_count} updated with working hours."
        ))
