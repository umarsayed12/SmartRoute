"""Estimate answer confidence using text signals and a short local self-check."""

import re

import httpx

from app.config import Tier, settings
from app.providers import ollama

_HEDGES = re.compile(
    r"\b(?:i(?:'m| am) not sure|i (?:don't|do not) know|as an ai)\b",
    re.IGNORECASE,
)


def heuristic_confidence(question: str, answer: str) -> float:
    """Penalize empty, short, hedged, or question-repeating answers on a 0-1 scale."""
    answer_text = answer.strip()
    answer_words = re.findall(r"\w+", answer_text.casefold())
    if not answer_words:
        return 0.0

    confidence = 1.0
    if len(answer_text) < 20 or len(answer_words) < 3:
        confidence -= 0.25
    if _HEDGES.search(answer_text.replace("\u2019", "'")):
        confidence -= 0.5
    question_words = re.findall(r"\w+", question.casefold())
    if question_words and answer_words == question_words:
        confidence -= 0.75
    return max(0.0, confidence)


async def self_check(model: str, question: str, answer: str) -> float:
    """Ask the local model for a 0-10 rating; use 0.5 if unavailable or invalid."""
    try:
        result = await ollama.chat(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Rate from 0 to 10 how confident you are that this answer "
                        "is correct and complete. Reply with only the number."
                    ),
                },
                {"role": "user", "content": f"Question:\n{question}\n\nAnswer:\n{answer}"},
            ],
            temperature=0.0,
            max_tokens=4,
            base_url=settings.OLLAMA_BASE_URL,
        )
        rating = int(result.content.strip())
    except (httpx.HTTPError, ValueError):
        return 0.5
    return rating / 10 if 0 <= rating <= 10 else 0.5


async def score(question: str, answer: str, tier: Tier) -> float:
    """Average both confidence signals, or return 1.0 at the highest enabled tier."""
    top_tier = [configured for configured in settings.TIERS if configured.enabled][-1]
    if tier.name == top_tier.name:
        return 1.0
    heuristic = heuristic_confidence(question, answer)
    checked = await self_check(tier.model, question, answer)
    return 0.5 * heuristic + 0.5 * checked