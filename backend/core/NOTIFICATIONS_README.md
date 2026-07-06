# `core/notifications.py` — explained in easy words

This file is the **one door** for every message the system sends to a patient —
SMS, email, WhatsApp, or voice. No agent sends messages on its own. They all go
through here.

---

## 1. Why one door?

Two big reasons:

1. **Respect "do not contact me."** A patient can opt out of a channel (say, "no
   SMS"). If every agent sent messages on its own, one of them would forget the
   opt-out and message the patient anyway. By forcing everything through ONE
   function, we check the opt-out rule in **one place, every time.** (This is the
   rule called NFR-8.)

2. **Easy to swap the real sender later.** Today we just print messages to the
   screen. Tomorrow we plug in Twilio (SMS) or SendGrid (email). Because there's
   one door, we change it in one spot — no agent needs to know.

---

## 2. The main function: `notify(...)`

```python
notify(patient, template, context, channel=None)
```

- `patient` — who we're messaging.
- `template` — the name of the message ("appointment_reminder", etc.).
- `context` — the data to fill into the message (name, date...).
- `channel` — sms / email / whatsapp / voice. If you don't pick one, it chooses
  automatically.

What it does, step by step:

1. **Pick a channel** (if you didn't). It looks at the patient's preferences and
   picks the first channel they allow.
2. **Check opt-out.** If the patient turned that channel OFF, it stops right here
   and returns `None`. Nothing is sent.
3. **Build the message text** from the template + the data.
4. **Figure out the address** — a phone number for sms/voice/whatsapp, or an
   email address for email.
5. **Save a record** in the `SentNotification` table and hand the message to the
   provider to actually send it.
6. **Return the record** so the caller knows it went out.

---

## 3. How opt-out works (the important part)

Each patient has `communication_preferences`, a simple on/off list per channel:

```json
{ "sms": false, "email": true, "voice": true, "whatsapp": false }
```

- `true`  = "yes, you can reach me this way."
- `false` = "no, don't message me here."

In `notify`, the check is one line:

```python
if prefs.get(channel) is False:
    return None
```

If the patient set that channel to `false`, we return `None` and send nothing.
If it's not set at all, we allow it (empty preferences = fine to contact).

---

## 4. The provider (who actually sends)

```python
class ConsoleProvider:
    def send(self, channel, recipient, content):
        print(f"[{channel}] -> {recipient}: {content}")
        return "console-msg-id"
```

Right now the "provider" just **prints** the message to the screen — perfect for
development, no real texts or emails go out. Later, a real Twilio/SendGrid
provider will have the exact same `send(...)` method, so `notify` won't change at
all — we just swap which provider it uses.

---

## 5. The templates

```python
def render_template(template, context, language="en"):
    body = _TEMPLATES.get(template, template)
    return body.format(**context)
```

A template is just a message with blanks to fill in, like:

```
"Hi {name}, your appointment is on {date}."
```

`render_template` finds the template by name and fills the blanks using the data
you passed. Right now the template list is basically empty — if a name isn't
found, it just uses the name itself so nothing crashes. Real messages (and
translations) get added later.

---

## 6. Full example

```python
from core.notifications import notify

# Patient allows email, blocked sms.
notify(patient, "appointment_reminder", {"name": "Asha", "date": "July 10"})
```

- No channel given → it auto-picks `email` (the first allowed one).
- Email is allowed → it builds the text, saves a `SentNotification` row, and the
  ConsoleProvider prints:
  `[email] -> asha@example.com: Hi Asha, your appointment is on July 10.`

If instead the patient had blocked email too, `notify` would return `None` and
send nothing.

---

## 7. Things to know / improve later

- **Real sending isn't wired yet** — ConsoleProvider only prints. That's on
  purpose for dev.
- **We don't save which template was used.** The `SentNotification` table has no
  `template` column yet. If you want that history, add a `template` field to the
  model later.
- **No retry if sending fails.** Good enough for now.

---

## 8. One-line summary

`core/notifications.py` is the **single exit door** for all patient messages: it
checks the patient's opt-out, builds the text, saves a record, and sends it —
using a fake "print to screen" sender for now that's easy to swap for a real one.
