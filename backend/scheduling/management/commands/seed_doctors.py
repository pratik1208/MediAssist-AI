from datetime import time

from django.core.management.base import BaseCommand

from scheduling.models import Doctor, Specialty


class Command(BaseCommand):
    help = "Seed the database with sample doctors"

    def handle(self, *args, **kwargs):
        doctors = [
            {
                "name": "Dr. John Smith",
                "specialization": Specialty.CARDIOLOGY,
                "working_hours_start": time(9, 0),
                "working_hours_end": time(17, 0),
            },
            {
                "name": "Dr. Sarah Johnson",
                "specialization": Specialty.DERMATOLOGY,
                "working_hours_start": time(10, 0),
                "working_hours_end": time(18, 0),
            },
            {
                "name": "Dr. Michael Brown",
                "specialization": Specialty.PEDIATRICS,
                "working_hours_start": time(8, 0),
                "working_hours_end": time(16, 0),
            },
            {
                "name": "Dr. Emily Davis",
                "specialization": Specialty.NEUROLOGY,
                "working_hours_start": time(9, 30),
                "working_hours_end": time(17, 30),
            },
            {
                "name": "Dr. David Wilson",
                "specialization": Specialty.ORTHOPEDICS,
                "working_hours_start": time(9, 0),
                "working_hours_end": time(17, 0),
            },
            {
                "name": "Dr. Lisa Taylor",
                "specialization": Specialty.GYNECOLOGY,
                "working_hours_start": time(10, 0),
                "working_hours_end": time(18, 0),
            },
            {
                "name": "Dr. James Moore",
                "specialization": Specialty.ENT,
                "working_hours_start": time(8, 30),
                "working_hours_end": time(16, 30),
            },
            {
                "name": "Dr. Jennifer White",
                "specialization": Specialty.GENERAL_MEDICINE,
                "working_hours_start": time(9, 0),
                "working_hours_end": time(17, 0),
            },
            {
                "name": "Dr. Robert Anderson",
                "specialization": Specialty.PSYCHIATRY,
                "working_hours_start": time(11, 0),
                "working_hours_end": time(19, 0),
            },
            {
                "name": "Dr. Maria Garcia",
                "specialization": Specialty.GASTROENTEROLOGY,
                "working_hours_start": time(9, 0),
                "working_hours_end": time(17, 0),
            },
        ]
        created_count = 0

        for doctor in doctors:
            _, created = Doctor.objects.get_or_create(
                name=doctor["name"],
                defaults={
                    "specialization": doctor["specialization"],
                    "working_hours_start": doctor["working_hours_start"],
                    "working_hours_end": doctor["working_hours_end"],
                },
            )

            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(f"{created_count} doctor(s) created successfully."))
