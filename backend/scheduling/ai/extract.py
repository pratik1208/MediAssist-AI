"""Booking-intent extraction for the scheduling agent.

Uses the shared AI door (core.ai). The provider (openai/anthropic/ollama) and
model are chosen centrally by core.ai — this agent just passes its own prompt and
tool. core.ai.call_tool always returns a clean, validated dict.
"""

from core.ai import call_tool

from scheduling.ai.prompts import SCHEDULING_SYSTEM_PROMPT
from scheduling.ai.tools import EXTRACT_BOOKING_INTENT_TOOL


def extract_intent(conversation_history) -> dict:
    """Return structured booking intent as a dict."""
    return call_tool(
        system=SCHEDULING_SYSTEM_PROMPT,
        messages=conversation_history,
        tool=EXTRACT_BOOKING_INTENT_TOOL,
    )
