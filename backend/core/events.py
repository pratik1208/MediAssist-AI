"""core.events — the in-process event dispatcher (ORCHESTRATION §3 Stage 2).

The backbone for all cross-agent side effects (SPEC_Core §2 rule 4). Agents
never deep-import each other; they react to events instead:

    # producer (any agent's services.py)
    from core.events import emit
    emit("priorauth.approved", patient_id=42, order_id=7)

    # consumer (another agent's apps.py ready())
    from core.events import subscribe

    @subscribe("priorauth.approved")
    def _book_approved_treatment(patient_id, order_id, **_):
        ...

Every emit() writes an EventLog row so there is a durable record of what fired,
whether it was processed, and which handlers (if any) failed.
"""

import logging
from collections import defaultdict

from core.models import EventLog

log = logging.getLogger("events")

# event_name -> list of handler callables
# "This is intended for internal use within this module."
_HANDLERS: dict[str, list] = defaultdict(list)


def subscribe(event_name: str):
    """Decorator: register a handler for an event name."""
    def register(fn):
        _HANDLERS[event_name].append(fn)
        return fn
    return register


def emit(event_name: str, **payload):
    """Record the event, then call every subscribed handler.

    One bad consumer never breaks the emitter: handler exceptions are logged and
    recorded on the EventLog row, but the loop continues.
    """
    entry = EventLog.objects.create(name=event_name, payload=payload)
    errors = []
    for handler in _HANDLERS[event_name]:
        try:
            handler(**payload)
        except Exception:  # one bad consumer never breaks the emitter
            log.exception("handler %s failed for %s", handler.__name__, event_name)
            errors.append(handler.__name__)
    entry.processed = True
    entry.error = ", ".join(errors) or ""
    entry.save(update_fields=["processed", "error"])
    return entry
