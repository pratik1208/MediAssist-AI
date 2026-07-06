"""Provider selection + per-provider model config for core.ai.

Everything here is driven by environment variables so no code change is needed
to switch provider or model. This module has NO scheduling/agent imports — core
is the foundation every agent depends on, never the other way around.
"""

import os

# Which backend core.ai talks to: "anthropic" | "openai" | "ollama".
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic")

# Per-provider model, each overridable via env.
# DEV DEFAULTS are the cheapest/smallest models to keep token cost low while
# building. To use a bigger model, comment the cheap line and uncomment the
# other one (or just set the value in .env — that always wins).

# --- OpenAI (current active provider) ---
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")   # cheap dev default
# OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")      # full model (pricier)

# --- Anthropic ---
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")  # cheap dev default
# ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")          # full model (pricier)

# --- Ollama (runs locally = no token cost at all) ---
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")    # tiny local default
# OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")     # larger local model

# Ollama runs locally and needs no API key — only a base URL. We read
# OLLAMA_BASE_URL (the host) from .env and append the chat endpoint.
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_URL = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"

