"""Extract inexpensive numeric signals from a text chat conversation."""

import re

FEATURE_ORDER = [
    "prompt_chars",
    "prompt_words",
    "num_turns",
    "has_code",
    "has_math",
    "question_count",
    "asks_reasoning",
    "asks_long_output",
    "non_ascii_ratio",
    "avg_word_len",
]

_CODE = re.compile(
    r"```|`[^`\n]+`|\b(?:python|javascript|typescript|sql|regex|code|debug)\b"
    r"|\b(?:def|class|function)\s+\w+\s*[(:{]|=>"
    r"|\b(?:const|let|var)\s+\w+\s*=",
    re.IGNORECASE,
)
_MATH = re.compile(
    r"\b(?:math|calculate|equation|algebra|calculus|integral|derivative|sum|solve)\b"
    r"|\d\s*(?:[+*/=^\-]|\*\*)\s*-?\d|[\u00d7\u00f7\u221a\u222b\u2211]",
    re.IGNORECASE,
)
_REASONING = re.compile(
    r"\b(?:explain|why|compare|analy[sz]e|step(?:\s+|-)by(?:\s+|-)step|prove)\b",
    re.IGNORECASE,
)
_LONG_OUTPUT = re.compile(
    r"\b(?:essay|detailed|comprehensive|write\s+a|generate\s+a)\b", re.IGNORECASE
)


def extract_features(messages: list[dict[str, str]]) -> dict[str, float]:
    """Measure all message contents, joined by newlines, in a stable feature order."""
    prompt = "\n".join(message["content"] for message in messages)
    words = prompt.split()
    return {
        "prompt_chars": float(len(prompt)),
        "prompt_words": float(len(words)),
        "num_turns": float(len(messages)),
        "has_code": float(bool(_CODE.search(prompt))),
        "has_math": float(bool(_MATH.search(prompt))),
        "question_count": float(prompt.count("?")),
        "asks_reasoning": float(bool(_REASONING.search(prompt))),
        "asks_long_output": float(bool(_LONG_OUTPUT.search(prompt))),
        "non_ascii_ratio": sum(ord(char) > 127 for char in prompt) / len(prompt) if prompt else 0.0,
        "avg_word_len": sum(len(word) for word in words) / len(words) if words else 0.0,
    }