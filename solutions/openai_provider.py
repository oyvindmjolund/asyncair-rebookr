"""OpenAI adapter: neutral types <-> OpenAI Chat Completions API.

Spot the differences vs. Anthropic:
  * The system prompt is just the first message (role "system").
  * Tool calls live in `message.tool_calls`; `arguments` is a JSON *string*.
  * Tool results go back as separate messages with role "tool".
  * Images are `image_url` parts, usually a data: URL.
  * Newer models want `max_completion_tokens`, not `max_tokens`.
"""
from __future__ import annotations

import json
import time
from typing import Iterator

import openai

from rebookr.llm.errors import BadRequest, ProviderUnavailable, RateLimited
from rebookr.llm.types import (ChatRequest, ChatResponse, ImagePart, StreamDone, StreamEvent, TextDelta,
                               TextPart, ToolCall, ToolResult, Usage)

FINISH_REASONS = {"stop": "end", "tool_calls": "tool_use", "length": "max_tokens"}


class OpenAIProvider:
    name = "openai"
    capabilities = {"tools", "vision", "streaming"}

    def __init__(self, api_key: str, base_url: str | None = None, timeout: float = 30.0, team: str = "anonymous"):
        self.client = openai.OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=0,
            default_headers={"x-asyncair-team": team},
        )

    # ---- translation: neutral -> OpenAI ----------------------------------------
    @staticmethod
    def _to_openai_messages(req: ChatRequest) -> list[dict]:
        out: list[dict] = []

        # TODO 1 (solution): the system prompt is simply the first message.
        if req.system:
            out.append({"role": "system", "content": req.system})

        for m in req.messages:
            if m.role == "assistant":
                text = "".join(p.text for p in m.parts if isinstance(p, TextPart))
                calls = [p for p in m.parts if isinstance(p, ToolCall)]
                msg: dict = {"role": "assistant", "content": text or None}
                if calls:
                    msg["tool_calls"] = [
                        {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                        for c in calls
                    ]
                out.append(msg)
                continue

            # TODO 2 (solution): each tool result becomes its own role="tool" message.
            for p in m.parts:
                if isinstance(p, ToolResult):
                    out.append({"role": "tool", "tool_call_id": p.tool_call_id, "content": p.content})

            content = []
            for p in m.parts:
                if isinstance(p, TextPart):
                    content.append({"type": "text", "text": p.text})
                elif isinstance(p, ImagePart):
                    content.append({"type": "image_url", "image_url": {"url": f"data:{p.media_type};base64,{p.data_b64}"}})
            if content:
                out.append({"role": "user", "content": content})
        return out

    def _params(self, req: ChatRequest, model: str) -> dict:
        params: dict = {
            "model": model,
            "messages": self._to_openai_messages(req),
            "max_completion_tokens": req.max_tokens,
        }
        if req.tools:
            params["tools"] = [
                {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.parameters}}
                for t in req.tools
            ]
        if req.temperature is not None:
            params["temperature"] = req.temperature
        return params

    # ---- translation: OpenAI -> neutral ----------------------------------------
    def _from_openai_response(self, resp, model: str, latency_ms: int) -> ChatResponse:
        choice = resp.choices[0]
        msg = choice.message

        # TODO 3 (solution): `arguments` arrives as a JSON string - parse it.
        calls = [ToolCall(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
                 for tc in (msg.tool_calls or [])]

        usage = resp.usage
        return ChatResponse(
            text=msg.content or "",
            tool_calls=calls,
            stop_reason=FINISH_REASONS.get(choice.finish_reason, "other"),
            usage=Usage(usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0),
            provider=self.name,
            model=model,
            latency_ms=latency_ms,
        )

    # ---- error mapping ---------------------------------------------------------
    def _map_error(self, e: Exception) -> Exception:
        if isinstance(e, openai.RateLimitError):
            return RateLimited(self.name, str(e))
        if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError)):
            return ProviderUnavailable(self.name, f"connection/timeout: {e}")
        if isinstance(e, openai.APIStatusError) and 400 <= e.status_code < 500:
            return BadRequest(self.name, f"HTTP {e.status_code}: {e}")   # our fault: don't fall back
        if isinstance(e, openai.APIError):
            # 5xx, or an error sent mid-stream (no HTTP status at all)
            return ProviderUnavailable(self.name, getattr(e, "message", str(e)))
        return e

    # ---- public API --------------------------------------------------------------
    def chat(self, req: ChatRequest, model: str) -> ChatResponse:
        t0 = time.perf_counter()
        try:
            resp = self.client.chat.completions.create(**self._params(req, model))
        except openai.OpenAIError as e:
            raise self._map_error(e) from e
        return self._from_openai_response(resp, model, int((time.perf_counter() - t0) * 1000))

    def stream(self, req: ChatRequest, model: str) -> Iterator[StreamEvent]:
        t0 = time.perf_counter()
        text, finish, usage = "", None, Usage()
        calls: dict[int, dict] = {}
        try:
            for chunk in self.client.chat.completions.create(
                    **self._params(req, model), stream=True, stream_options={"include_usage": True}):
                if chunk.usage:
                    usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta.content:
                    text += delta.content
                    yield TextDelta(delta.content)
                for tc in delta.tool_calls or []:      # tool calls arrive in fragments
                    slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                    slot["id"] = tc.id or slot["id"]
                    if tc.function:
                        slot["name"] = tc.function.name or slot["name"]
                        slot["args"] += tc.function.arguments or ""
                finish = choice.finish_reason or finish
        except openai.OpenAIError as e:
            raise self._map_error(e) from e
        yield StreamDone(ChatResponse(
            text=text,
            tool_calls=[ToolCall(c["id"], c["name"], json.loads(c["args"] or "{}")) for c in calls.values()],
            stop_reason=FINISH_REASONS.get(finish, "other"),
            usage=usage, provider=self.name, model=model,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        ))
