"""OpenAI implementation of the core.ai contract.

Generic: takes system / messages / tool as arguments. Translates our canonical
tool dict (name/description/input_schema) into OpenAI's function-tool shape.
"""

import json

from openai import OpenAI
from langsmith import traceable

from core.ai.providers import OPENAI_MODEL

client = OpenAI()  # reads OPENAI_API_KEY


def _to_openai_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


@traceable(name="call_tool", run_type="llm")
def call_tool_openai(system: str, messages: list[dict], tool: dict, max_tokens: int = 2048) -> dict:
    """Force one tool call and return its arguments as a dict."""
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, *messages],
        tools=[_to_openai_tool(tool)],
        tool_choice={"type": "function", "function": {"name": tool["name"]}},
    )
    tool_calls = resp.choices[0].message.tool_calls
    if not tool_calls:
        raise ValueError("Model did not return a tool call.")
    return json.loads(tool_calls[0].function.arguments)


@traceable(name="stream_reply", run_type="llm")
def stream_reply_openai(system: str, messages: list[dict], max_tokens: int = 2048):
    """Yield text deltas for SSE chat endpoints."""
    stream = client.chat.completions.create(
        model=OPENAI_MODEL,
        max_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, *messages],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
