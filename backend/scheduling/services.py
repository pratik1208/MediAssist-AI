from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from core.events import emit
from scheduling.models import Appointment, Waitlist


def _emit_booked(appointment):
    """Announce a new booking so subscribers (e.g. confirmations) can react."""
    emit(
        "appointment.booked",
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_id=appointment.doctor_id,
        doctor_name=appointment.doctor.name,
        start=appointment.start_time.isoformat(),
    )

URGENCY_RANK = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


def generate_blocks(working_start, working_end, date):
    start = datetime.combine(date, working_start)
    end = datetime.combine(date, working_end)

    slot_duration = timedelta(minutes=20)

    blocks = []

    while start + slot_duration <= end:
        blocks.append((start, start + slot_duration))
        start += slot_duration

    return blocks


WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def find_available_slots(doctor, date_from, date_to):

    # Doctor.working_hours is per-day JSON, e.g.
    # {"mon": [["09:00", "17:00"]], ...} — build candidate blocks for every
    # working window that falls inside [date_from, date_to].
    candidates = []
    day = date_from.date()
    while day <= date_to.date():
        if day.isoformat() not in (doctor.holidays or []):
            windows = (doctor.working_hours or {}).get(WEEKDAY_KEYS[day.weekday()], [])
            for window_start, window_end in windows:
                candidates += generate_blocks(
                    datetime.strptime(window_start, "%H:%M").time(),
                    datetime.strptime(window_end, "%H:%M").time(),
                    day,
                )
        day += timedelta(days=1)

    # Django's clock, not the OS clock — must agree with the timezone the
    # timeframe parser used to build the candidate days.
    now = timezone.localtime().replace(tzinfo=None)
    candidates = [
        (start, end)
        for start, end in candidates
        if start >= date_from and end <= date_to and start > now
    ]

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

    appointment = Appointment.objects.create(
        doctor=doctor,
        patient=patient,
        start_time=start,
        end_time=end,
        status="booked",
        reason=reason,
        urgency=urgency,
    )
    _emit_booked(appointment)
    return appointment

# Either everything succeeds or everything is rolled back.
@transaction.atomic
def promote_next_waitlisted(
    doctor,
    freed_start,
    freed_end,
):

    candidate = Waitlist.objects.filter(
        specialty=doctor.specialty,
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
        reason="Promoted from waitlist",
        urgency=patient.urgency,
    )

    patient.status = "booked"
    patient.save()

    _emit_booked(appointment)
    return appointment


@transaction.atomic
def cancel_appointment(appointment):

    appointment.status = "cancelled"
    appointment.save()

    emit(
        "appointment.cancelled",
        appointment_id=appointment.id,
        patient_id=appointment.patient_id,
        doctor_name=appointment.doctor.name,
        start=appointment.start_time.isoformat(),
    )

    promote_next_waitlisted(
        appointment.doctor,
        appointment.start_time,
        appointment.end_time,
    )

    return appointment
