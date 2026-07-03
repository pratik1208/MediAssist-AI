import json

from openai import OpenAI
from langsmith import traceable
from scheduling.ai.prompts import SCHEDULING_SYSTEM_PROMPT
from scheduling.ai.tools import EXTRACT_BOOKING_INTENT_TOOL

client = OpenAI()


@traceable(
    name="Extract Booking Intent",
    run_type="llm",)
def extract_intent_openai(conversation_history):

    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {
                "role": "system",
                "content": SCHEDULING_SYSTEM_PROMPT,
            },
            *conversation_history,
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": EXTRACT_BOOKING_INTENT_TOOL["name"],
                    "description": EXTRACT_BOOKING_INTENT_TOOL["description"],
                    "parameters": EXTRACT_BOOKING_INTENT_TOOL["input_schema"],
                },
            }
        ],
        tool_choice={
            "type": "function",
            "function": {
                "name": "extract_booking_intent",
            },
        },
    )

    tool_calls = response.choices[0].message.tool_calls

    if not tool_calls:
        raise ValueError("Model did not return a tool call.")

    return json.loads(tool_calls[0].function.arguments)
