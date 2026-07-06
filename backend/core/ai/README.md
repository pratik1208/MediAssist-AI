# `core/ai/` — the single AI door (explained from basics)

This folder is the **one place in the whole project that talks to an LLM**
(Anthropic, OpenAI, or Ollama). Every one of the 9 agents asks the AI through
here — they never import an AI SDK themselves.

If you read nothing else: agents write
`from core.ai import call_tool, stream_reply, strict_tool` and that's it.

---

## 1. Why does this folder exist at all?

The project has **9 agents** (Scheduling, Registration, Triage, …). Every agent
needs to talk to an LLM. Imagine each agent writing its own AI code:

- The model name `"claude-opus-4-8"` would be copy-pasted into 9+ files.
  Upgrade day = edit 9 files and pray you didn't miss one.
- Switching provider (Anthropic → OpenAI) = rewrite 9 agents.
- Tracing, error handling, tool formatting = duplicated 9 times, all slightly
  different.

So we build **one door**. All AI access flows through this single folder. This
is the *Adapter pattern* — also called "one door" or "single source of truth."
The rule from `SPEC_Core.md`:

> "`core/ai` — the only place that touches the AI SDK."

---

## 2. What do agents actually need from an LLM? (only two things)

Everything the agents do boils down to **two operations**, so this folder
exposes exactly two functions.

### a) `call_tool(...)` → "give me structured data"

When a patient says *"my chest hurts, can I see someone tomorrow?"*, the agent
needs a clean Python dict back, NOT a paragraph:

```python
{"symptom": "chest pain", "urgency": "high", "specialty": "Cardiology"}
```

Deterministic code can branch on a dict; it can't branch on prose. This is
called **tool use** (a.k.a. *function calling*): you hand the model a schema and
force it to fill in exactly that shape.

### b) `stream_reply(...)` → "give me words to show the patient"

For the chat window we want text to appear word-by-word (the "typing" effect),
not a frozen screen for 4 seconds. `stream_reply` yields little pieces of text
("deltas") as they arrive.

That's the entire job: **get structured data**, and **stream text**.

---

## 3. The files, one by one (basic first)

```
core/ai/
├── __init__.py           ← the DOOR agents import from + the router
├── providers.py          ← config: which provider? which model?
├── anthropic_client.py   ← how to do the 2 jobs using Anthropic
├── openai_client.py      ← how to do the 2 jobs using OpenAI
└── ollama_client.py      ← how to do the 2 jobs using a local model
```

The big idea: **separate WHAT from HOW.**
- `__init__.py` = *what* the agents can do (stable, never changes).
- each `*_client.py` = *how* one provider does it (swappable).

### `providers.py` — the config file

```python
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
OPENAI_MODEL    = os.getenv("OPENAI_MODEL", "gpt-4.1")
OLLAMA_MODEL    = os.getenv("OLLAMA_MODEL", "llama3.1")
```

Every choice — provider AND model — comes from **environment variables**, never
hardcoded. This is the payoff of the whole design: to move the entire project
from Anthropic to OpenAI you change **one line in `.env`**
(`AI_PROVIDER=openai`) and restart. Zero code changes.

### `__init__.py` — the door + the router

Two jobs:

1. **`strict_tool(name, description, properties, required)`** — a helper that
   builds the tool schema in one consistent shape so agents don't hand-write
   nested JSON. The important bits it adds:
   - `additionalProperties: False` → the model may not invent extra keys.
   - `required: [...]` → these keys must always be present.

   Together these make the returned dict safe to trust.

2. **The router** (`call_tool`, `stream_reply`) — reads `AI_PROVIDER` and sends
   the call to the right provider's file:

   ```python
   def call_tool(system, messages, tool, max_tokens=2048):
       if AI_PROVIDER == "anthropic":
           from core.ai.anthropic_client import call_tool_anthropic
           return call_tool_anthropic(system, messages, tool, max_tokens)
       if AI_PROVIDER == "openai":
           ...
   ```

   The agent calling `call_tool` never sees this branching. That is the whole
   point — the complexity is hidden behind the door.

### `anthropic_client.py` / `openai_client.py` / `ollama_client.py`

Each one implements the **same two functions** for a single provider. They look
similar but differ in annoying provider-specific details:

| Detail | Anthropic | OpenAI |
|---|---|---|
| Where the system prompt goes | separate `system=` param | first message in the list |
| What a tool call returns | `block.input` (already a dict) | a JSON **string** → needs `json.loads()` |
| Tool `strict` key | not accepted (we strip it) | accepted |

**This is exactly why the one-door design matters** — all this inconsistency is
locked inside these three files. No agent ever needs to know that OpenAI returns
a string while Anthropic returns a dict.

---

## 4. Two design choices that look odd (and why)

### a) Tool "translation"

Agents write their tool **once** in the canonical shape
(`name` / `description` / `input_schema`). But each provider wants it formatted
differently, so each client has a tiny translator (`_to_openai_tool`,
`_clean_tool`) that reshapes it. The agent writes it once; the clients adapt it.

### b) Imports *inside* the functions (lazy imports)

Normally you import at the top of a file. Here the router imports the client
*inside* the `if` branch:

```python
if AI_PROVIDER == "anthropic":
    from core.ai.anthropic_client import call_tool_anthropic
```

**Why:** `openai_client.py` runs `client = OpenAI()` when it loads, which
**crashes if `OPENAI_API_KEY` is missing.** If we imported all three clients at
the top, then simply doing `from core.ai import call_tool` would try to build all
three clients and demand ALL three API keys — even though you use only one
provider. Importing lazily means **only the selected provider's client is ever
built**, so `core.ai` stays importable everywhere (tests, migrations, admin)
without every key present.

---

## 5. The one hard rule: core never imports from an agent

You will see NO `from scheduling...` (or any agent) in this folder. The
dependency direction is strictly one-way:

```
scheduling ─┐
registration┤
triage      ├──►  core   (core knows nothing about them)
...         ┘
```

`core` is the foundation the whole project sits on. If `core` imported from
`scheduling`, loading `core` would load `scheduling`, which loads `core`… a
**circular import** Python can't resolve — and `core` would stop being reusable.
So core depends on nothing above it.

---

## 6. How an agent uses this folder

```python
from core.ai import call_tool, strict_tool

# 1. Define the shape you want back (write this ONCE).
BOOKING_TOOL = strict_tool(
    "extract_booking_intent",
    "Extract structured booking details from what the patient said.",
    {
        "symptom":  {"type": "string"},
        "urgency":  {"type": "string", "enum": ["low", "medium", "high", "emergency"]},
        "specialty":{"type": "string"},
    },
    required=["symptom", "urgency"],
)

# 2. Ask the AI. You do NOT know or care which provider answers.
result = call_tool(
    system=SCHEDULING_SYSTEM_PROMPT,   # this agent's own prompt
    messages=conversation_history,     # the chat so far
    tool=BOOKING_TOOL,                 # this agent's own tool
)
# result -> {"symptom": "...", "urgency": "high", "specialty": "Cardiology"}

# 3. Your deterministic code decides what to do with the dict.
```

For chat text instead of structured data:

```python
from core.ai import stream_reply

for delta in stream_reply(system=PROMPT, messages=history):
    send_to_browser(delta)   # word-by-word typing effect
```

---

## 7. One-line mental model

**`core/ai` is a universal remote for LLMs**: agents press two buttons
(`call_tool`, `stream_reply`); `providers.py` decides which TV (Anthropic /
OpenAI / Ollama) the remote is pointed at; the `*_client.py` files know the
button codes for each TV. Change the TV in `.env`, and every agent's remote
keeps working unchanged.

---

## Setup checklist

- [ ] Put the right API key in `.env` for whichever provider you use
      (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`; Ollama needs a local server).
- [ ] Set `AI_PROVIDER` in `.env` (default here is `anthropic`). Note your
      `scheduling` app currently defaults to `openai` — make them agree.
- [ ] Import only from `core.ai` in every agent. Never import an AI SDK directly
      outside this folder.
