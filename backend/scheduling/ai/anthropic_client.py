from anthropic import Anthropic
from langsmith import traceable

from scheduling.ai.prompts import SCHEDULING_SYSTEM_PROMPT
from scheduling.ai.tools import EXTRACT_BOOKING_INTENT_TOOL

client = Anthropic()


@traceable(
    name="Extract Booking Intent",
    run_type="llm",
)
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
