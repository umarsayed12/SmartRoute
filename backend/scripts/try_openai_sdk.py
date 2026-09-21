"""Demonstrate the official OpenAI SDK against a running SmartRoute gateway."""

import json

from openai import OpenAI


def main() -> None:
    """Request a real small-tier answer and print its routing metadata."""
    with OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed",
        timeout=180.0,
        max_retries=0,
    ) as client:
        response = client.chat.completions.create(
            model="smartroute/auto",
            messages=[{
                "role": "user",
                "content": "Explain what an LLM gateway does in one short sentence.",
            }],
            max_tokens=64,
        )
    print(response.choices[0].message.content)
    print(json.dumps((response.model_extra or {}).get("smartroute"), indent=2))


if __name__ == "__main__":
    main()