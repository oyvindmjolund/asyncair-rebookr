"""Provider-neutral types. Nothing in here knows about any vendor.

This is the contract the rest of Rebookr talks to. Adapters translate
between these types and each vendor's SDK.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union


@dataclass
class TextPart:
    text: str


@dataclass
class ImagePart:
    media_type: str      # e.g. "image/png"
    data_b64: str        # base64, no data: prefix


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


Part = Union[TextPart, ImagePart, ToolCall, ToolResult]


@dataclass
class Message:
    role: Literal["user", "assistant"]
    parts: list[Part]

    @staticmethod
    def user(text: str) -> "Message":
        return Message("user", [TextPart(text)])


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict     # JSON Schema for the arguments


@dataclass
class ChatRequest:
    messages: list[Message]
    system: str | None = None
    tools: list[ToolSpec] = field(default_factory=list)
    max_tokens: int = 1024
    temperature: float | None = None

    @property
    def needs_vision(self) -> bool:
        return any(isinstance(p, ImagePart) for m in self.messages for p in m.parts)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


StopReason = Literal["end", "tool_use", "max_tokens", "other"]


@dataclass
class ChatResponse:
    text: str
    tool_calls: list[ToolCall]
    stop_reason: StopReason
    usage: Usage
    provider: str
    model: str
    latency_ms: int = 0
    attempts: list[str] = field(default_factory=list)   # filled in by the router

    def as_message(self) -> Message:
        parts: list[Part] = []
        if self.text:
            parts.append(TextPart(self.text))
        parts.extend(self.tool_calls)
        return Message("assistant", parts)


@dataclass
class TextDelta:
    """Streaming event: a chunk of text."""
    text: str


@dataclass
class StreamDone:
    """Streaming event: the stream finished; full response attached."""
    response: ChatResponse


StreamEvent = Union[TextDelta, StreamDone]
