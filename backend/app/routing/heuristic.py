"""Choose a model tier with ordered, explainable prompt-feature rules."""


def pick_tier(features: dict[str, float]) -> tuple[str, str]:
    """Return the tier and first matching rule, testing large-tier rules first."""
    words = features["prompt_words"]
    has_code = bool(features["has_code"])
    asks_reasoning = bool(features["asks_reasoning"])

    if features["asks_long_output"]:
        return "large", "Prompt asks for long or detailed output."
    if has_code and asks_reasoning and words > 200:
        return "large", "Prompt combines code and reasoning with over 200 words."
    if has_code:
        return "medium", "Prompt contains code or programming cues."
    if asks_reasoning:
        return "medium", "Prompt asks for explanation or reasoning."
    if words > 120:
        return "medium", "Prompt contains over 120 words."
    if words < 12:
        return "small", "Prompt has fewer than 12 words and no code or reasoning cues."
    return "small", "Prompt has at most 120 words and no higher-tier cues."