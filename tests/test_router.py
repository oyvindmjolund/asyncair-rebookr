"""Router behaviour, tested with in-memory fake providers (no network)."""
import pytest

from rebookr.llm import (AllProvidersFailed, BadRequest, ChatRequest, ChatResponse, ImagePart, Message,
                         ModelRouter, ProviderUnavailable, Usage)


class Fake:
    def __init__(self, name, fail_with=None, capabilities=("tools", "vision", "streaming")):
        self.name, self.fail_with, self.capabilities, self.calls = name, fail_with, set(capabilities), 0

    def chat(self, req, model):
        self.calls += 1
        if self.fail_with:
            raise self.fail_with(self.name, "boom")
        return ChatResponse("hi", [], "end", Usage(), self.name, model)


CFG = {
    "providers": {"a": {"smart": "a-1"}, "b": {"smart": "b-1"}, "c": {"smart": "c-1"}},
    "routes": {"main": {"chain": ["a:smart", "b:smart", "c:smart"]}},
    "resilience": {"retries_per_provider": 0, "breaker_failures": 2, "breaker_cooldown_seconds": 60},
}
REQ = ChatRequest([Message.user("hello")])


def test_uses_first_healthy_provider():
    r = ModelRouter({"a": Fake("a"), "b": Fake("b"), "c": Fake("c")}, CFG).chat(REQ, "main")
    assert r.provider == "a"


def test_falls_back_on_outage():
    r = ModelRouter({"a": Fake("a", ProviderUnavailable), "b": Fake("b"), "c": Fake("c")}, CFG).chat(REQ, "main")
    assert r.provider == "b"
    assert r.attempts[0].startswith("a:")


def test_does_not_fall_back_on_our_own_bug():
    with pytest.raises(BadRequest):
        ModelRouter({"a": Fake("a", BadRequest), "b": Fake("b"), "c": Fake("c")}, CFG).chat(REQ, "main")


def test_all_down_raises():
    providers = {n: Fake(n, ProviderUnavailable) for n in "abc"}
    with pytest.raises(AllProvidersFailed):
        ModelRouter(providers, CFG).chat(REQ, "main")


def test_circuit_breaker_stops_hammering_a_dead_provider():
    a = Fake("a", ProviderUnavailable)
    router = ModelRouter({"a": a, "b": Fake("b"), "c": Fake("c")}, CFG)
    for _ in range(5):
        router.chat(REQ, "main")
    assert a.calls == 2   # breaker opened after 2 failures


def test_skips_provider_without_vision():
    req = ChatRequest([Message("user", [ImagePart("image/png", "AAAA")])])
    r = ModelRouter({"a": Fake("a", capabilities=("tools",)), "b": Fake("b"), "c": Fake("c")}, CFG).chat(req, "main")
    assert r.provider == "b"
