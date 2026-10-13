"""Rebookr: the passenger-facing agent loop.

Note what's NOT in this file: any vendor SDK. The agent talks to the router.
"""
from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rebookr.llm import ChatRequest, ImagePart, Message, ModelRouter, StreamDone, TextDelta, TextPart, ToolResult
from rebookr.tools import TOOLS, run_tool

MAX_TOOL_ROUNDS = 5


@dataclass
class Turn:
    answer: str
    trace: list[str] = field(default_factory=list)   # which providers were tried / answered
    tools_called: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


class Rebookr:
    def __init__(self, router: ModelRouter, system_prompt: str):
        self.router = router
        self.system = system_prompt
        self.history: list[Message] = []

    def ask(self, text: str, image_path: str | None = None, route: str | None = None,
            on_text: Callable[[str], None] | None = None) -> Turn:
        parts: list = [TextPart(text)]
        if image_path:
            data = base64.b64encode(Path(image_path).read_bytes()).decode()
            parts.append(ImagePart(mimetypes.guess_type(image_path)[0] or "image/png", data))
            route = route or "vision"
        self.history.append(Message("user", parts))
        route = route or "rebooking"
        trace: list[str] = []
        tools_called: list[str] = []
        tok_in = tok_out = 0

        for _ in range(MAX_TOOL_ROUNDS):
            req = ChatRequest(messages=self.history, system=self.system, tools=TOOLS, max_tokens=2000)
            if on_text:
                resp = None
                for ev in self.router.stream(req, route=route):
                    if isinstance(ev, TextDelta):
                        on_text(ev.text)
                    elif isinstance(ev, StreamDone):
                        resp = ev.response
            else:
                resp = self.router.chat(req, route=route)
            trace.append(f"{resp.provider}/{resp.model} {resp.latency_ms}ms  [{' → '.join(resp.attempts)}]")
            tok_in += resp.usage.input_tokens
            tok_out += resp.usage.output_tokens
            self.history.append(resp.as_message())

            if not resp.tool_calls:
                return Turn(resp.text, trace, tools_called, tok_in, tok_out)

            results = []
            for call in resp.tool_calls:
                trace.append(f"   🔧 {call.name}({call.arguments})")
                tools_called.append(call.name)
                results.append(ToolResult(call.id, run_tool(call.name, call.arguments)))
            self.history.append(Message("user", results))

        return Turn("Sorry, I couldn't finish that request. A human agent will follow up.", trace, tools_called, tok_in, tok_out)
