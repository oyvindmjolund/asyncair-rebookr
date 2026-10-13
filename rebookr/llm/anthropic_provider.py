"""Anthropic adapter: neutral types <-> Anthropic Messages API.

Things worth pointing out in class:
  * `system` is a top-level parameter, not a message.
  * `max_tokens` is REQUIRED.
  * Content is a list of typed blocks; tool calls are `tool_use` blocks and
    tool results go back as `tool_result` blocks inside a *user* message.
  * Tool schemas use `input_schema`.
"""
from __future__ import annotations

import time
from typing import Iterator

import anthropic

from rebookr.llm.errors import BadRequest, ProviderUnavailable, RateLimited
from rebookr.llm.types import (ChatRequest, ChatResponse, ImagePart, StreamDone, StreamEvent, TextDelta,
                               TextPart, ToolCall, ToolResult, Usage)

STOP_REASONS = {"end_turn": "end", "tool_use": "tool_use", "max_tokens": "max_tokens", "stop_sequence": "end"}


class AnthropicProvider:
    name = "anthropic"
    capabilities = {"tools", "vision", "streaming"}

    def __init__(self, api_key: str, base_url: str | None = None, timeout: float = 30.0, team: str = "anonymous"):
        self.client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,            # the ROUTER owns retries/fallback, not the SDK
            default_headers={"x-asyncair-team": team},
        )

    # ---- translation: neutral -> Anthropic -------------------------------------
    @staticmethod
    def _to_anthropic_messages(req: ChatRequest) -> list[dict]:
        out = []
        for m in req.messages:
            blocks = []
            for p in m.parts:
                if isinstance(p, TextPart):
                    blocks.append({"type": "text", "text": p.text})
                elif isinstance(p, ImagePart):
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": p.media_type, "data": p.data_b64}})
                elif isinstance(p, ToolCall):
                    blocks.append({"type": "tool_use", "id": p.id, "name": p.name, "input": p.arguments})
                elif isinstance(p, ToolResult):
                    blocks.append({"type": "tool_result", "tool_use_id": p.tool_call_id, "content": p.content, "is_error": p.is_error})
            out.append({"role": m.role, "content": blocks})
        return out

    def _params(self, req: ChatRequest, model: str) -> dict:
        params: dict = {
            "model": model,
            "max_tokens": req.max_tokens,
            "messages": self._to_anthropic_messages(req),
        }
        if req.system:
            params["system"] = req.system
        if req.tools:
            params["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in req.tools]
        if req.temperature is not None:
            params["temperature"] = req.temperature
        return params

    # ---- translation: Anthropic -> neutral -------------------------------------
    def _from_anthropic(self, msg, model: str, latency_ms: int) -> ChatResponse:
        text = "".join(b.text for b in msg.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in msg.content if b.type == "tool_use"]
        return ChatResponse(
            text=text,
            tool_calls=calls,
            stop_reason=STOP_REASONS.get(msg.stop_reason, "other"),
            usage=Usage(msg.usage.input_tokens, msg.usage.output_tokens),
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
        )

    # ---- error mapping ---------------------------------------------------------
    def _map_error(self, e: Exception) -> Exception:
        if isinstance(e, anthropic.RateLimitError):
            return RateLimited(self.name, str(e))
        if isinstance(e, (anthropic.APIConnectionError, anthropic.APITimeoutError)):
            return ProviderUnavailable(self.name, f"connection/timeout: {e}")
        if isinstance(e, anthropic.APIStatusError) and 400 <= e.status_code < 500:
            return BadRequest(self.name, f"HTTP {e.status_code}: {e}")   # our fault: don't fall back
        if isinstance(e, anthropic.APIError):
            # 500/503/529 overloaded, or an error event sent mid-stream (arrives with HTTP 200)
            return ProviderUnavailable(self.name, getattr(e, "message", str(e)))
        return e

    # ---- public API --------------------------------------------------------------
    def chat(self, req: ChatRequest, model: str) -> ChatResponse:
        t0 = time.perf_counter()
        try:
            msg = self.client.messages.create(**self._params(req, model))
        except anthropic.AnthropicError as e:
            raise self._map_error(e) from e
        return self._from_anthropic(msg, model, int((time.perf_counter() - t0) * 1000))

    def stream(self, req: ChatRequest, model: str) -> Iterator[StreamEvent]:
        t0 = time.perf_counter()
        try:
            with self.client.messages.stream(**self._params(req, model)) as s:
                for text in s.text_stream:
                    yield TextDelta(text)
                final = s.get_final_message()
        except anthropic.AnthropicError as e:
            raise self._map_error(e) from e
        yield StreamDone(self._from_anthropic(final, model, int((time.perf_counter() - t0) * 1000)))
