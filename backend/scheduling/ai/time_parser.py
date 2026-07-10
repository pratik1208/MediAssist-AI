from datetime import datetime, time, timedelta

from django.utils import timezone

# Time-of-day windows. A phrase may combine these with any day reference,
# e.g. "tomorrow morning", "monday evening if possible".
DAY_PARTS = {
    "morning": (time(8, 0), time(12, 0)),
    "afternoon": (time(12, 0), time(17, 0)),
    "evening": (time(17, 0), time(20, 0)),
    "night": (time(17, 0), time(20, 0)),
}

WEEKDAYS = [
    "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
]

ASAP_PHRASES = ["asap", "as soon as possible", "right away", "immediately", "urgently"]

FULL_DAY = (time(0, 0), time(23, 59))


def _day_span(day, part):
    """(start, end) datetimes for one calendar day, narrowed to a day part."""
    part_start, part_end = DAY_PARTS.get(part, FULL_DAY)
    return (
        datetime.combine(day, part_start),
        datetime.combine(day, part_end),
    )


def parse_preferred_timeframe(preferred_timeframe):
    """
    Convert a natural language timeframe into (date_from, date_to).

    The model passes through the patient's own words, so matching is
    substring-based ("sometime tomorrow morning please" still works).
    Raises ValueError for phrases it can't place — the handler turns
    that into a clarification question, never a crash.
    """

    if not preferred_timeframe:
        return None, None

    today = timezone.localtime().date()
    timeframe = preferred_timeframe.lower().strip()

    part = next((p for p in DAY_PARTS if p in timeframe), None)

    if "tomorrow" in timeframe:
        return _day_span(today + timedelta(days=1), part)

    if "today" in timeframe or any(p in timeframe for p in ASAP_PHRASES):
        return _day_span(today, part)

    for index, weekday in enumerate(WEEKDAYS):
        if weekday in timeframe:
            days_ahead = (index - today.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7  # "monday" said on a Monday means next week's
            return _day_span(today + timedelta(days=days_ahead), part)

    if "next week" in timeframe:
        next_monday = today + timedelta(days=7 - today.weekday())
        return (
            datetime.combine(next_monday, time(0, 0)),
            datetime.combine(next_monday + timedelta(days=6), time(23, 59)),
        )

    if "week" in timeframe:  # "this week", "later this week", "in the week"
        sunday = today + timedelta(days=6 - today.weekday())
        return (
            datetime.combine(today, time(0, 0)),
            datetime.combine(sunday, time(23, 59)),
        )

    raise ValueError(f"Unsupported timeframe: {preferred_timeframe}")
