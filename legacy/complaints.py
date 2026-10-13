import anthropic

from legacy._client import BASE_URL


def summarise_complaint(text: str) -> str:
    client = anthropic.Anthropic(api_key="mock-key", base_url=BASE_URL)
    resp = client.messages.create(model="claude-sonnet-5-5", max_tokens=300,
                                  messages=[{"role": "user", "content": f"Summarise this complaint: {text}"}])
    return resp.content[0].text
