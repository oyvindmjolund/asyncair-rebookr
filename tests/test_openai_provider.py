"""EXERCISE: make these pass by finishing rebookr/llm/openai_provider.py.

    pytest tests/test_openai_provider.py -v

Bonus: when they pass, the Azure adapter works too. Why?
"""
import json

import pytest

from rebookr.llm import ChatRequest, Message, ToolResult
from rebookr.llm.azure_provider import AzureOpenAIProvider
from rebookr.llm.openai_provider import OpenAIProvider
from rebookr.tools import TOOLS


@pytest.fixture
def gpt(tower):
    return OpenAIProvider("mock-key", base_url=f"{tower}/openai/v1", timeout=5)


def test_todo1_system_prompt_is_first_message():
    msgs = OpenAIProvider._to_openai_messages(ChatRequest([Message.user("Hi")], system="You are Rebookr."))
    assert msgs[0] == {"role": "system", "content": "You are Rebookr."}
    assert msgs[1]["role"] == "user"


def test_todo2_tool_results_become_tool_messages():
    req = ChatRequest([Message("user", [ToolResult("call_1", '{"ok": true}'), ToolResult("call_2", '{"ok": false}')])])
    msgs = OpenAIProvider._to_openai_messages(req)
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in tool_msgs] == ["call_1", "call_2"]


def test_todo3_tool_call_arguments_are_parsed(gpt):
    r = gpt.chat(ChatRequest([Message.user("My flight KRS to OSL was cancelled")], tools=TOOLS), "gpt-test")
    assert r.stop_reason == "tool_use"
    assert r.tool_calls[0].name == "search_flights"
    assert isinstance(r.tool_calls[0].arguments, dict), "arguments must be a dict, not a JSON string"


def test_full_round_trip(gpt):
    req = ChatRequest([Message.user("My flight KRS to OSL was cancelled")], system="You are Rebookr.", tools=TOOLS)
    r = gpt.chat(req, "gpt-test")
    req.messages += [r.as_message(), Message("user", [ToolResult(r.tool_calls[0].id, json.dumps({"flights": []}))])]
    r2 = gpt.chat(req, "gpt-test")
    assert r2.text and r2.stop_reason == "end"


def test_bonus_azure_works_for_free(tower):
    azure = AzureOpenAIProvider("mock-key", endpoint=f"{tower}/azure", api_version="2024-10-21", timeout=5)
    r = azure.chat(ChatRequest([Message.user("Hello")], system="You are Rebookr."), "rebookr-smart")
    assert r.provider == "azure" and r.text
