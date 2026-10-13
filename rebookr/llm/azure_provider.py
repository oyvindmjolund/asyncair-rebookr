"""Azure OpenAI adapter.

Punchline for the class: once the OpenAI adapter exists, Azure is ~15 lines.
Azure hosts (mostly) the same models behind the same wire format. What changes:
  * a different client with `azure_endpoint` + `api_version`
  * `model` is YOUR DEPLOYMENT NAME, not the model name
  * you pick the region (EU data residency), quotas are per deployment,
    and an extra content filter can reject requests with HTTP 400.
"""
from __future__ import annotations

import openai

from rebookr.llm.openai_provider import OpenAIProvider


class AzureOpenAIProvider(OpenAIProvider):
    name = "azure"

    def __init__(self, api_key: str, endpoint: str, api_version: str, timeout: float = 30.0, team: str = "anonymous",
                 key_header: str | None = None):
        headers = {"x-asyncair-team": team}
        if key_header:
            # An AI gateway (Azure API Management) in front of Foundry may expect the key
            # under another header name than "api-key", e.g. "x-api-key".
            headers[key_header] = api_key
        self.client = openai.AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version=api_version,
            timeout=timeout,
            max_retries=0,
            default_headers=headers,
        )
