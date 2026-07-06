"""core.ai — the single AI door for every agent.

Agents import ONLY from here:

    from core.ai import call_tool, stream_reply, strict_tool

They never import a specific provider client or the Anthropic/OpenAI SDK
directly. The provider is chosen at runtime by AI_PROVIDER (see providers.py).

Provider clients are imported lazily inside each function so that importing
core.ai does not require every SDK/API key to be present — only the selected
provider's client is ever constructed.
"""

from core.ai.providers import AI_PROVIDER


def strict_tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """Build the canonical tool schema every agent passes to call_tool()."""
    return {
        "name": name,
        "description": description,
        "strict": True,  # honored by OpenAI; stripped for Anthropic
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def call_tool(system: str, messages: list[dict], tool: dict, max_tokens: int = 2048) -> dict:
    """Force one strict tool call and return its validated input dict."""
    if AI_PROVIDER == "anthropic":
        from core.ai.anthropic_client import call_tool_anthropic
        return call_tool_anthropic(system, messages, tool, max_tokens)
    if AI_PROVIDER == "openai":
        from core.ai.openai_client import call_tool_openai
        return call_tool_openai(system, messages, tool, max_tokens)
    if AI_PROVIDER == "ollama":
        from core.ai.ollama_client import call_tool_ollama
        return call_tool_ollama(system, messages, tool, max_tokens)
    raise ValueError(f"Unsupported AI_PROVIDER: {AI_PROVIDER}")


def stream_reply(system: str, messages: list[dict], max_tokens: int = 2048):
    """Yield text deltas for SSE chat endpoints."""
    if AI_PROVIDER == "anthropic":
        from core.ai.anthropic_client import stream_reply_anthropic
        return stream_reply_anthropic(system, messages, max_tokens)
    if AI_PROVIDER == "openai":
        from core.ai.openai_client import stream_reply_openai
        return stream_reply_openai(system, messages, max_tokens)
    if AI_PROVIDER == "ollama":
        from core.ai.ollama_client import stream_reply_ollama
        return stream_reply_ollama(system, messages, max_tokens)
    raise ValueError(f"Unsupported AI_PROVIDER: {AI_PROVIDER}")
