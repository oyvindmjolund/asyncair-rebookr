import json

import anthropic

from legacy._client import BASE_URL
from rebookr.tools import run_tool


def rebook(question: str) -> str:
    client = anthropic.Anthropic(api_key="mock-key", base_url=BASE_URL)
    messages = [{"role": "user", "content": question}]
    tools = [{
        "name": "search_flights",
        "description": "Find alternative flights",
        "input_schema": {"type": "object", "properties": {"origin": {"type": "string"}, "destination": {"type": "string"}}},
    }]
    while True:
        resp = client.messages.create(model="claude-sonnet-5-5", max_tokens=800,
                                      system="You are Rebookr.", messages=messages, tools=tools)
        if resp.stop_reason != "tool_use":
            return resp.content[0].text
        messages.append({"role": "assistant", "content": resp.content})
        results = [{"type": "tool_result", "tool_use_id": b.id, "content": run_tool(b.name, b.input)}
                   for b in resp.content if b.type == "tool_use"]
        messages.append({"role": "user", "content": results})
