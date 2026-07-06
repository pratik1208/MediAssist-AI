"""Anthropic implementation of the core.ai contract.

Generic: takes system / messages / tool as arguments. No agent-specific prompts
or tools live here — each agent passes its own.
"""

from anthropic import Anthropic
from langsmith import traceable

from core.ai.providers import ANTHROPIC_MODEL

client = Anthropic()  # reads ANTHROPIC_API_KEY


def _clean_tool(tool: dict) -> dict:
    """Anthropic tools accept only name/description/input_schema.

    Our canonical strict_tool() adds a "strict" key (useful for OpenAI); strip
    anything Anthropic doesn't understand.
    """
    return {
        "name": tool["name"],
        "description": tool["description"],
        "input_schema": tool["input_schema"],
    }


@traceable(name="call_tool", run_type="llm")
def call_tool_anthropic(system: str, messages: list[dict], tool: dict, max_tokens: int = 2048) -> dict:
    """Force one tool call and return its validated input dict."""
    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=max_tokens,
        system=system,
        tools=[_clean_tool(tool)],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=messages,
    )
    block = next(b for b in resp.content if b.type == "tool_use")
    return block.input


@traceable(name="stream_reply", run_type="llm")
def stream_reply_anthropic(system: str, messages: list[dict], max_tokens: int = 2048):
    """Yield text deltas for SSE chat endpoints."""
    with client.messages.stream(
        model=ANTHROPIC_MODEL, max_tokens=max_tokens, system=system, messages=messages,
    ) as stream:
        yield from stream.text_stream
