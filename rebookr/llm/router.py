"""The model router: pick a provider+model per task, fall back when one fails.

    router.chat(request, route="rebooking")

Each route is an ordered chain like ["anthropic:smart", "openai:smart", "azure:smart"].
For each candidate the router:
  1. skips it if its circuit breaker is open (it failed a lot recently)
  2. skips it if it lacks a capability the request needs (e.g. vision)
  3. tries it (optionally retrying with backoff)
  4. on a *retryable* error moves to the next candidate;
     on a non-retryable error (our bug, e.g. HTTP 400) stops immediately.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Iterator

from rebookr.llm.errors import AllProvidersFailed, LLMError, StreamInterrupted
from rebookr.llm.types import ChatRequest, ChatResponse, StreamDone, StreamEvent, TextDelta


@dataclass
class CircuitBreaker:
    failures_to_open: int = 3
    cooldown_seconds: float = 30.0
    consecutive_failures: int = 0
    opened_at: float | None = None

    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_seconds:
            self.opened_at = None            # half-open: let one request through to test
            self.consecutive_failures = self.failures_to_open - 1
            return False
        return True

    def record_success(self) -> None:
        self.consecutive_failures, self.opened_at = 0, None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.failures_to_open:
            self.opened_at = time.monotonic()


class ModelRouter:
    def __init__(self, providers: dict, cfg: dict, log: Callable[[str], None] | None = None):
        self.providers = providers
        self.models = cfg["providers"]
        self.routes = {name: r["chain"] for name, r in cfg["routes"].items()}
        res = cfg.get("resilience", {})
        self.retries = res.get("retries_per_provider", 0)
        self.backoff = res.get("backoff_seconds", 0.5)
        self.breakers = {name: CircuitBreaker(res.get("breaker_failures", 3), res.get("breaker_cooldown_seconds", 30))
                         for name in providers}
        self.log = log or (lambda msg: None)

    # ------------------------------------------------------------------------
    def _candidates(self, route: str, req: ChatRequest, attempts: list[str]):
        if route not in self.routes:
            raise KeyError(f"Unknown route '{route}'. Known: {sorted(self.routes)}")
        for entry in self.routes[route]:
            pname, alias = entry.split(":")
            provider = self.providers.get(pname)
            if provider is None:
                attempts.append(f"{pname}: not configured")
                continue
            if self.breakers[pname].is_open():
                attempts.append(f"{pname}: circuit open, skipped")
                self.log(f"⏭  {pname} skipped (circuit breaker open)")
                continue
            if req.needs_vision and "vision" not in provider.capabilities:
                attempts.append(f"{pname}: no vision")
                continue
            if req.tools and "tools" not in provider.capabilities:
                attempts.append(f"{pname}: no tool calling")
                continue
            yield pname, provider, self.models[pname][alias]

    def _handle_failure(self, pname: str, e: Exception, attempts: list[str]) -> None:
        if isinstance(e, NotImplementedError):
            # The exercise adapter isn't finished yet - treat as unavailable so the app keeps working.
            attempts.append(f"{pname}: adapter unfinished ({e})")
            self.log(f"🚧 {pname} adapter unfinished: {e}")
            return
        if isinstance(e, LLMError) and not e.retryable:
            raise e
        self.breakers[pname].record_failure()
        attempts.append(f"{pname}: {type(e).__name__}")
        self.log(f"✗  {pname} failed: {type(e).__name__} -> falling back")

    # ------------------------------------------------------------------------
    def chat(self, req: ChatRequest, route: str = "rebooking") -> ChatResponse:
        attempts: list[str] = []
        for pname, provider, model in self._candidates(route, req, attempts):
            for attempt in range(self.retries + 1):
                try:
                    resp = provider.chat(req, model)
                except (LLMError, NotImplementedError) as e:
                    if isinstance(e, LLMError) and e.retryable and attempt < self.retries:
                        time.sleep(self.backoff * (2 ** attempt))      # exponential backoff
                        continue
                    self._handle_failure(pname, e, attempts)
                    break
                self.breakers[pname].record_success()
                attempts.append(f"{pname}: ok")
                resp.attempts = attempts
                return resp
        raise AllProvidersFailed(route, attempts)

    def stream(self, req: ChatRequest, route: str = "rebooking") -> Iterator[StreamEvent]:
        """Fallback is only safe BEFORE the first token reaches the user.

        Once text is on screen, switching provider would produce a second,
        different answer glued onto the first. So after the first token we
        raise StreamInterrupted and let the caller decide (e.g. retry the
        whole turn non-streaming, or show "connection lost").
        """
        attempts: list[str] = []
        for pname, provider, model in self._candidates(route, req, attempts):
            emitted = False
            try:
                for ev in provider.stream(req, model):
                    if isinstance(ev, TextDelta):
                        emitted = True
                    if isinstance(ev, StreamDone):
                        self.breakers[pname].record_success()
                        attempts.append(f"{pname}: ok")
                        ev.response.attempts = attempts
                    yield ev
                return
            except (LLMError, NotImplementedError) as e:
                if emitted:
                    self.breakers[pname].record_failure()
                    raise StreamInterrupted(pname, f"died mid-stream: {e}") from e
                self._handle_failure(pname, e, attempts)
        raise AllProvidersFailed(route, attempts)
