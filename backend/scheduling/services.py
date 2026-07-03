from datetime import datetime, timedelta

from django.db import transaction

from scheduling.models import Appointment, Waitlist

URGENCY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

from datetime import datetime, timedelta


def generate_blocks(working_start, working_end, date):
    start = datetime.combine(date, working_start)
    end = datetime.combine(date, working_end)

    slot_duration = timedelta(minutes=20)

    blocks = []

    while start + slot_duration <= end:
        blocks.append((start, start + slot_duration))
        start += slot_duration

    return blocks


def find_available_slots(doctor, date_from, date_to):

    candidates = generate_blocks(
        doctor.working_hours_start,
        doctor.working_hours_end,
        date_from.date(),
    )

    booked = Appointment.objects.filter(
        doctor=doctor,
        status="booked",
        start_time__lt=date_to,
        end_time__gt=date_from,
    )

    available = []

    for candidate_start, candidate_end in candidates:

        overlap = booked.filter(
            start_time__lt=candidate_end,
            end_time__gt=candidate_start,
        ).exists()

        if not overlap:
            available.append((candidate_start, candidate_end))

    return available


def book_appointment(
    doctor,
    patient,
    start,
    end,
    reason,
    urgency,
):

    return Appointment.objects.create(
        doctor=doctor,
        patient=patient,
        start_time=start,
        end_time=end,
        status="booked",
        reason_text=reason,
        urgency=urgency,
    )


@transaction.atomic
def promote_next_waitlisted(
    doctor,
    freed_start,
    freed_end,
):

    candidate = Waitlist.objects.filter(
        specialization=doctor.specialization,
        status="waiting",
    ).order_by("created_at")

    candidate = sorted(
        candidate,
        key=lambda x: (
            URGENCY_RANK.get(x.urgency, 99),
            x.created_at,
        ),
    )

    if not candidate:
        return None

    patient = candidate[0]

    appointment = Appointment.objects.create(
        doctor=doctor,
        patient=patient.patient,
        start_time=freed_start,
        end_time=freed_end,
        status="booked",
        reason_text="Promoted from waitlist",
        urgency=patient.urgency,
    )

    patient.status = "booked"
    patient.save()

    return appointment


@transaction.atomic
def cancel_appointment(appointment):

    appointment.status = "cancelled"
    appointment.save()

    promote_next_waitlisted(
        appointment.doctor,
        appointment.start_time,
        appointment.end_time,
    )

    return appointment
