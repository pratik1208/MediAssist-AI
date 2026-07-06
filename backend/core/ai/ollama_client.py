"""Ollama (local) implementation of the core.ai contract.

Generic: takes system / messages / tool as arguments. Talks to a local Ollama
server over HTTP. Useful for offline dev with no API costs.
"""

import requests
from langsmith import traceable

from core.ai.providers import OLLAMA_MODEL, OLLAMA_URL


def _to_ollama_tool(tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool["description"],
            "parameters": tool["input_schema"],
        },
    }


@traceable(name="call_tool", run_type="llm")
def call_tool_ollama(system: str, messages: list[dict], tool: dict, max_tokens: int = 2048) -> dict:
    """Force one tool call and return its arguments as a dict."""
    resp = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system}, *messages],
            "tools": [_to_ollama_tool(tool)],
            "stream": False,
        },
        timeout=60,
    )
    resp.raise_for_status()
    tool_calls = resp.json().get("message", {}).get("tool_calls")
    if not tool_calls:
        raise ValueError("Model did not return a tool call.")
    # Ollama returns arguments already parsed as a dict.
    return tool_calls[0]["function"]["arguments"]


@traceable(name="stream_reply", run_type="llm")
def stream_reply_ollama(system: str, messages: list[dict], max_tokens: int = 2048):
    """Yield text deltas for SSE chat endpoints."""
    import json

    with requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "messages": [{"role": "system", "content": system}, *messages],
            "stream": True,
        },
        timeout=60,
        stream=True,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if not line:
                continue
            delta = json.loads(line).get("message", {}).get("content")
            if delta:
                yield delta
