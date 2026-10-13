import anthropic

from legacy._client import BASE_URL


def read_boarding_pass(png_b64: str) -> str:
    client = anthropic.Anthropic(api_key="mock-key", base_url=BASE_URL)
    resp = client.messages.create(
        model="claude-sonnet-5-5", max_tokens=300,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": png_b64}},
            {"type": "text", "text": "Read this boarding pass."},
        ]}],
    )
    return resp.content[0].text
