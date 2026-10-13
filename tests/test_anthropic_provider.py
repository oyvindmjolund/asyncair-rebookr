"""Reference adapter - these should already pass."""
import json

import pytest

from rebookr.llm import ChatRequest, Message, ProviderUnavailable, StreamDone, TextDelta, ToolResult
from rebookr.llm.anthropic_provider import AnthropicProvider
from rebookr.tools import TOOLS
from tests.conftest import set_chaos


@pytest.fixture
def claude(tower):
    return AnthropicProvider("mock-key", base_url=f"{tower}/anthropic", timeout=5)


def test_plain_text(claude):
    r = claude.chat(ChatRequest([Message.user("Hello")], system="You are Rebookr."), "claude-test")
    assert r.provider == "anthropic" and r.text and r.stop_reason == "end"


def test_tool_call_round_trip(claude):
    req = ChatRequest([Message.user("My flight KRS to OSL was cancelled")], tools=TOOLS)
    r = claude.chat(req, "claude-test")
    assert r.stop_reason == "tool_use"
    call = r.tool_calls[0]
    assert call.name == "search_flights" and isinstance(call.arguments, dict)

    req.messages += [r.as_message(), Message("user", [ToolResult(call.id, json.dumps({"flights": []}))])]
    r2 = claude.chat(req, "claude-test")
    assert r2.stop_reason == "end" and r2.text


def test_streaming(claude):
    events = list(claude.stream(ChatRequest([Message.user("Hello")]), "claude-test"))
    assert any(isinstance(e, TextDelta) for e in events)
    assert isinstance(events[-1], StreamDone)


def test_outage_is_normalised(claude, tower):
    set_chaos(tower, "anthropic", "down")
    with pytest.raises(ProviderUnavailable):
        claude.chat(ChatRequest([Message.user("Hello")]), "claude-test")
