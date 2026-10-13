"""The one interface every provider adapter implements."""
from __future__ import annotations

from typing import Iterator, Protocol

from rebookr.llm.types import ChatRequest, ChatResponse, StreamEvent


class LLMProvider(Protocol):
    name: str                      # "anthropic", "openai", "azure"
    capabilities: set[str]         # subset of {"tools", "vision", "streaming"}

    def chat(self, req: ChatRequest, model: str) -> ChatResponse:
        """One request, one complete response."""
        ...

    def stream(self, req: ChatRequest, model: str) -> Iterator[StreamEvent]:
        """Yield TextDelta events, then exactly one StreamDone."""
        ...
