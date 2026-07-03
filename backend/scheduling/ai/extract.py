from scheduling.ai.providers import AI_PROVIDER

from scheduling.ai.openai_client import extract_intent_openai
from scheduling.ai.anthropic_client import extract_intent_anthropic
from scheduling.ai.ollama_client import extract_intent_ollama


def extract_intent(conversation_history):
    if AI_PROVIDER == "openai":
        return extract_intent_openai(conversation_history)

    if AI_PROVIDER == "anthropic":
        return extract_intent_anthropic(conversation_history)

    if AI_PROVIDER == "ollama":
        return extract_intent_ollama(conversation_history)

    raise ValueError(f"Unsupported provider: {AI_PROVIDER}")
