from anthropic import Anthropic
from scheduling.ai.tools import EXTRACT_BOOKING_INTENT_TOOL
from scheduling.ai.prompts import SCHEDULING_SYSTEM_PROMPT

client = Anthropic()


def extract_intent_anthropic(conversation_history):

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=512,
        system=SCHEDULING_SYSTEM_PROMPT,
        messages=conversation_history,
        tools=[EXTRACT_BOOKING_INTENT_TOOL],
        tool_choice={
            "type": "tool",
            "name": "extract_booking_intent",
        },
    )

    return response
