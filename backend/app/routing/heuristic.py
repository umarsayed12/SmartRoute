"""Choose a model tier with ordered, explainable prompt-feature rules."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.routing.features import CurrentTurnScope, HistoryScope


def _pick_tier_dual_scope(
    current: CurrentTurnScope,
    history: HistoryScope,
) -> tuple[str, str]:
    """Evaluate context-aware dual-scope cascade in strict hierarchical order."""
    # Cascade Step 1: Conversational short-circuit (greetings, acknowledgments, closures)
    if current.is_pure_conversational and not (current.has_code or current.has_math):
        return (
            "small",
            "Conversational greeting, acknowledgment, or closure short-circuits to small tier.",
        )

    # Cascade Step 2: Standalone current turn evaluation
    if current.asks_long_output:
        return "large", "Current turn asks for long or detailed output."

    if (current.has_code or current.has_math) and current.asks_reasoning and current.word_count > 200:
        return "large", "Current turn combines code and reasoning with over 200 words."

    if current.has_code:
        return "medium", "Current turn contains code or programming cues."

    if current.has_math:
        return "medium", "Current turn contains mathematical formulas or calculations."

    if current.asks_reasoning:
        return "medium", "Current turn asks for explanation or reasoning."

    if current.is_short_technical and not (
        history.prior_turn_has_code
        or history.history_has_code
        or history.prior_turn_has_math
        or getattr(history, "history_has_math", False)
        or history.prior_turn_asks_reasoning
        or history.history_asks_reasoning
    ):
        return "medium", "Prompt contains concise technical query or instruction."

    # Cascade Step 3: Conditional history inheritance (anaphoric or short technical follow-ups)
    if current.is_anaphoric or current.is_short_technical:
        # Check if the follow-up inherits large-tier code + reasoning complexity
        if (
            (history.prior_turn_has_code or history.history_has_code or current.has_code)
            and (history.prior_turn_asks_reasoning or history.history_asks_reasoning or current.asks_reasoning)
            and (
                current.word_count > 200
                or (current.word_count + history.weighted_word_count > 200 and current.word_count > 50)
            )
        ):
            return "large", "Contextual follow-up combines code and reasoning exceeding 200 words."

        if history.prior_turn_has_code or history.history_has_code:
            return "medium", "Contextual follow-up referencing prior code."

        if history.prior_turn_has_math or getattr(history, "history_has_math", False):
            return "medium", "Contextual follow-up referencing prior mathematical derivation."

        if history.prior_turn_asks_reasoning or history.history_asks_reasoning:
            return "medium", "Contextual follow-up referencing prior explanation or reasoning."

        if current.is_short_technical:
            return "medium", "Prompt contains concise technical query or instruction."

    # Cascade Step 4 / Tail fallback safety check
    if current.is_short_technical and (history.history_has_code or history.prior_turn_has_code):
        return "medium", "Contextual follow-up referencing prior code."

    # Cascade Step 4: Default word count boundaries on current turn
    if current.word_count > 120:
        return "medium", "Current turn contains over 120 words."

    if current.word_count < 12:
        return "small", "Current turn has fewer than 12 words and no code or reasoning cues."

    return "small", "Current turn has at most 120 words and no higher-tier cues."


def _pick_tier_legacy(features: dict[str, float] | Any) -> tuple[str, str]:
    """Evaluate legacy monolithic features for backward compatibility."""
    words = (
        features.get("prompt_words", 0.0)
        if isinstance(features, dict)
        else getattr(features, "prompt_words", 0.0)
    )
    has_code = bool(
        features.get("has_code", 0.0)
        if isinstance(features, dict)
        else getattr(features, "has_code", 0.0)
    )
    asks_reasoning = bool(
        features.get("asks_reasoning", 0.0)
        if isinstance(features, dict)
        else getattr(features, "asks_reasoning", 0.0)
    )
    asks_long_output = bool(
        features.get("asks_long_output", 0.0)
        if isinstance(features, dict)
        else getattr(features, "asks_long_output", 0.0)
    )

    if asks_long_output:
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


def pick_tier(features: dict[str, float] | Any) -> tuple[str, str]:
    """Choose a model tier with context-aware cascade or legacy fallback.

    If `features` carries dual-scope attributes (`current_turn` and `history`),
    the context-aware cascade is executed to prevent multi-turn context bleed.
    Otherwise, falls back to legacy prompt-feature rules for 100% backward
    compatibility with plain dictionary inputs.
    """
    current = getattr(features, "current_turn", None)
    history = getattr(features, "history", None)
    if current is not None and history is not None:
        return _pick_tier_dual_scope(current, history)
    return _pick_tier_legacy(features)
