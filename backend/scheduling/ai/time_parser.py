from datetime import datetime, time, timedelta
from django.utils import timezone

def parse_preferred_timeframe(preferred_timeframe):
    """
    Convert a natural language timeframe into
    (date_from, date_to).
    """

    if not preferred_timeframe:
        return None, None

    now = timezone.now()

    timeframe = preferred_timeframe.lower().strip()

    if timeframe == "today":
        start = datetime.combine(now.date(), time(0, 0))
        end = datetime.combine(now.date(), time(23, 59))
        return start, end
    tomorrow = timezone.now().date() + timedelta(days=1)
    if timeframe == "tomorrow":
        tomorrow = now.date() + timedelta(days=1)

        start = datetime.combine(tomorrow, time(0, 0))
        end = datetime.combine(tomorrow, time(23, 59))
        return start, end

    if timeframe == "tomorrow morning":
        tomorrow = now.date() + timedelta(days=1)

        return (
            datetime.combine(tomorrow, time(8, 0)),
            datetime.combine(tomorrow, time(12, 0)),
        )

    if timeframe == "tomorrow afternoon":
        tomorrow = now.date() + timedelta(days=1)

        return (
            datetime.combine(tomorrow, time(12, 0)),
            datetime.combine(tomorrow, time(17, 0)),
        )

    if timeframe == "tomorrow evening":
        tomorrow = now.date() + timedelta(days=1)

        return (
            datetime.combine(tomorrow, time(17, 0)),
            datetime.combine(tomorrow, time(20, 0)),
        )

    raise ValueError(f"Unsupported timeframe: {preferred_timeframe}")
