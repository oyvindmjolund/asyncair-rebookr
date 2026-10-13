"""Builds provider adapters from config. The ONLY place that knows about keys and URLs."""
from __future__ import annotations

import os
import sys

from rebookr.llm.anthropic_provider import AnthropicProvider
from rebookr.llm.azure_provider import AzureOpenAIProvider
from rebookr.llm.openai_provider import OpenAIProvider


def build_providers(cfg: dict) -> dict:
    team = cfg.get("team", "anonymous")
    providers: dict = {}

    if cfg["mode"] == "mock":
        url = cfg["mock"]["url"]
        timeout = cfg["mock"].get("timeout_seconds", 5)
        providers["anthropic"] = AnthropicProvider("mock-key", base_url=f"{url}/anthropic", timeout=timeout, team=team)
        providers["openai"] = OpenAIProvider("mock-key", base_url=f"{url}/openai/v1", timeout=timeout, team=team)
        providers["azure"] = AzureOpenAIProvider("mock-key", endpoint=f"{url}/azure",
                                                 api_version=cfg["providers"]["azure"]["api_version"], timeout=timeout, team=team)
        return providers

    timeout = cfg.get("live", {}).get("timeout_seconds", 60)
    if os.environ.get("ANTHROPIC_API_KEY"):
        providers["anthropic"] = AnthropicProvider(os.environ["ANTHROPIC_API_KEY"], timeout=timeout, team=team)
    if os.environ.get("OPENAI_API_KEY"):
        providers["openai"] = OpenAIProvider(os.environ["OPENAI_API_KEY"], timeout=timeout, team=team)
    if os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        providers["azure"] = AzureOpenAIProvider(
            os.environ["AZURE_OPENAI_API_KEY"], endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", cfg["providers"]["azure"]["api_version"]),
            timeout=timeout, team=team, key_header=os.environ.get("AZURE_OPENAI_KEY_HEADER"))
    missing = {"anthropic", "openai", "azure"} - providers.keys()
    if missing:
        print(f"[registry] live mode: no credentials for {sorted(missing)}; they will be skipped.", file=sys.stderr)
    return providers
