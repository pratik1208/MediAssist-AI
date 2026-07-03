import requests

from scheduling.ai.prompts import SCHEDULING_SYSTEM_PROMPT
from scheduling.ai.tools import EXTRACT_BOOKING_INTENT_TOOL


def extract_intent_ollama(conversation_history):
    response = requests.post(
        "http://localhost:11434/api/chat",
        json={
            "model": "llama3.1",
            "messages": [
                {
                    "role": "system",
                    "content": SCHEDULING_SYSTEM_PROMPT,
                },
                *conversation_history,
            ],
            "tools": [EXTRACT_BOOKING_INTENT_TOOL],
            "stream": False,
        },
        timeout=60,
    )

    response.raise_for_status()

    return response.json()
