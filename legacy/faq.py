import anthropic

from legacy._client import BASE_URL


def answer_faq(question: str) -> str:
    client = anthropic.Anthropic(api_key="mock-key", base_url=BASE_URL)
    resp = client.messages.create(
        model="claude-haiku-5-5",
        max_tokens=500,
        system="You are AsyncAir's FAQ bot.",
        messages=[{"role": "user", "content": question}],
    )
    return resp.content[0].text
