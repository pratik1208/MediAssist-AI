# `core/events.py` — explained in easy words

This small file is what lets your 9 agents work together **without needing to
know about each other.** Let's go slow and simple.

---

## 1. What problem does it solve?

Often one agent needs another agent to do something. Example:

- Prior-Auth approves a treatment → Scheduling should offer to book it.
- Registration verifies a patient → Triage can continue its work.

The easy-looking way is to let one agent call the other directly:

```python
# ❌ inside priorauth
from scheduling.services import offer_booking_for_order
offer_booking_for_order(patient_id, order_id)
```

But this is a trap:

- Now **Prior-Auth depends on Scheduling.** If you change Scheduling, Prior-Auth
  can break.
- If Scheduling also needs Prior-Auth, Python gets stuck (they import each
  other — this is a "circular import").
- If 3 agents care about the same thing, the sender has to call all 3 by hand.
  Add a 4th, and you edit the sender again. Painful.

**The better way:** the sender just shouts *"hey, this happened!"* and doesn't
care who is listening. Any agent that cares can listen on its own. Nobody calls
anybody directly.

---

## 2. Think of it like a radio 📻

- **`emit("priorauth.approved", ...)`** = a radio station saying something out
  loud. It doesn't know who is listening.
- **`@subscribe("priorauth.approved")`** = an agent turning on a radio and
  tuning to that station. When the station speaks, every tuned-in radio hears it.
- **`EventLog`** = a notebook that writes down every announcement — what was
  said, when, and whether any listener had a problem.

The sender and the listeners never talk to each other directly. This file sits
in the middle and passes the message along.

---

## 3. Going through the file, part by part

### Part A — the list of listeners: `_HANDLERS`

```python
from collections import defaultdict
_HANDLERS: dict[str, list] = defaultdict(list)
```

Think of this as a **phone book**. It maps an event name to a list of functions
that want to be called when that event happens:

```python
{
    "priorauth.approved": [book_treatment, notify_patient],
    "patient.verified":   [resume_triage],
}
```

`defaultdict(list)` just means: if you look up an event name that nobody signed
up for yet, you get an empty list instead of an error. Saves us from writing
"does this exist?" checks everywhere.

### Part B — signing up a listener: `subscribe`

```python
def subscribe(event_name: str):
    def register(fn):
        _HANDLERS[event_name].append(fn)
        return fn
    return register
```

It looks scary but it does ONE simple thing: *"add this function to the list for
this event."*

You use it like this:

```python
@subscribe("priorauth.approved")
def book_treatment(patient_id, order_id, **_):
    services.offer_booking_for_order(patient_id, order_id)
```

That `@subscribe(...)` line on top means: *"call this function whenever
`priorauth.approved` happens."* That's it. The function is now a listener.

### Part C — making the announcement: `emit`

```python
def emit(event_name: str, **payload):
    entry = EventLog.objects.create(name=event_name, payload=payload)
    errors = []
    for handler in _HANDLERS[event_name]:
        try:
            handler(**payload)
        except Exception:
            log.exception("handler %s failed for %s", handler.__name__, event_name)
            errors.append(handler.__name__)
    entry.processed = True
    entry.error = ", ".join(errors) or ""
    entry.save(update_fields=["processed", "error"])
    return entry
```

In plain words, `emit` does this:

1. **Write it down first.** It saves a row in the `EventLog` table saying "this
   event happened, here's the data." Even if the server dies right after, you
   still have proof it happened. At this point `processed` is still `False`.

2. **Find the listeners and call them.** It looks up everyone who signed up for
   this event and calls them one by one, handing over the data.

3. **Protect against a bad listener.** The `try / except` is the key safety net:
   > If one listener crashes, it must NOT stop the others or crash the sender.

   So if a listener throws an error, we just note it down and move on to the next
   listener. The sender never feels it.

4. **Mark it done.** After all listeners have run, it sets `processed = True` and
   writes down the names of any listeners that failed (or an empty string if all
   went fine).

---

## 4. What do the `**` stars mean?

You'll see `**payload` and `**_`. Don't panic, they're simple:

- `emit("x.happened", patient_id=42, order_id=7)` → the `**payload` **gathers**
  those extras into a dict: `{"patient_id": 42, "order_id": 7}`.
- `handler(**payload)` → the `**` **spreads** the dict back out, so it calls
  `handler(patient_id=42, order_id=7)`.
- In `def book_treatment(patient_id, order_id, **_):` → the `**_` means *"if
  extra stuff is passed that I didn't ask for, just ignore it."* The `_` is a
  common way of saying "I don't care about this." It keeps old listeners working
  even if the event gets new fields later.

---

## 5. Important: a listener only works if its file gets loaded

A listener only counts if its `@subscribe` line actually ran. And that line runs
only when Python loads the file it's in. If the file is never loaded, the radio
was never turned on, and `emit` finds nobody listening.

That's why each agent signs up its listeners in `apps.py` inside `ready()` —
Django runs this automatically when it starts:

```python
# scheduling/apps.py
class SchedulingConfig(AppConfig):
    name = "scheduling"
    def ready(self):                      # runs once when Django starts
        from core.events import subscribe
        from scheduling import services

        @subscribe("priorauth.approved")
        def book_treatment(patient_id, order_id, **_):
            services.offer_booking_for_order(patient_id, order_id)
```

So the order is: **Django starts → each app's `ready()` runs → all listeners
sign up → now `emit` can reach them.**

👉 Tip: if an event "isn't working," first check that the listener's file is
actually being loaded.

---

## 6. Full example, start to finish

1. Prior-Auth finishes and calls
   `emit("priorauth.approved", patient_id=42, order_id=7)`.
2. `emit` saves an `EventLog` row (`processed=False`).
3. It finds Scheduling's `book_treatment` listener.
4. It calls it → the appointment gets booked. No error.
5. `emit` marks the row `processed=True`, `error=""`, and saves.
6. Prior-Auth had no idea Scheduling was involved. Tomorrow you can add a second
   listener (like "send a confirmation SMS") just by writing another
   `@subscribe` — **without touching Prior-Auth at all.**

---

## 7. Why save to `EventLog` and not just the memory list?

The `_HANDLERS` phone book lives in memory and is wiped when you restart the
server. The `EventLog` table is saved in the database forever. That gives you:

- **Debugging** — "did this event even fire?" → just check the table.
- **Seeing failures** — the `error` column tells you which listener broke, so
  problems don't stay hidden.
- **Room to grow** — later, when there's lots of traffic, you can process these
  rows in the background instead of right away. The table is already a to-do
  list waiting for that upgrade.

---

## 8. Things to keep in mind (current limits)

- **It runs right away, in the same process.** A slow listener slows down the
  sender. That's fine for now; we'll improve it when traffic grows.
- **Listeners must be loaded.** If an app's `ready()` doesn't import the
  listener, it silently won't work.
- **No auto-retry.** A failed listener is written to `error` but not tried again.
  Retries come later with the background-worker upgrade.

---

## 9. One-line summary

`core/events.py` is a **radio station for your agents**: one agent announces
something with `emit`, other agents listen with `@subscribe`, every announcement
is saved in `EventLog`, and one broken listener never ruins it for the rest.
