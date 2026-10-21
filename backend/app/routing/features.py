"""Extract inexpensive numeric signals and dual-scope context from chat conversations."""

from dataclasses import dataclass
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

# Legacy feature detection regexes (kept 100% identical for backward compatibility)
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
    r"\b(?:essay|detailed|comprehensive|write\s+a|generate\s+a)\b",
    re.IGNORECASE,
)

# Conversational praise patterns (with demonstrative pronouns/verbs)
_PRAISE_PATTERN_STR = (
    r"(?:that|it|this)\s+(?:looks?|seems?|is|was|sounds?)\s+(?:(?:really|super|very|pretty|quite|so)\s+)?(?:clean|great|good|awesome|nice|cool|perfect|fine|neat|helpful|wonderful|amazing|slick|fantastic|brilliant|correct|clear)"
    r"|(?:that's|thats|it's)\s+(?:(?:really|super|very|pretty|quite|so)\s+)?(?:clean|great|good|awesome|nice|cool|perfect|fine|neat|helpful|wonderful|amazing|slick|fantastic|brilliant|correct|clear)"
    r"|(?:looks?|seems?|sounds?)\s+(?:(?:really|super|very|pretty|quite|so)\s+)?(?:clean|great|good|awesome|nice|cool|perfect|fine|neat|helpful|wonderful|amazing|slick|fantastic|brilliant)"
    r"|(?:that|it|this)\s+works(?:\s+(?:for\s+me|well|great|perfectly))?"
    r"|works\s+(?:for\s+me|well|great|perfectly)"
    r"|(?:that|it)\s+helped(?:\s+(?:a\s+lot|a\s+ton|me))?"
    r"|that\s+solved\s+it"
)

# Conversational marker detection
_CONVERSATIONAL_PHRASES = (
    r"hi|hello|hey|howdy|greetings|good\s+(?:morning|afternoon|evening|day)|hi\s+there|hey\s+there|hello\s+there|hiya|yo"
    r"|thanks(?:\s+a\s+lot)?|thank\s+you(?:\s+(?:so|very)\s+much)?|thx"
    r"|ok|okay|k|got\s+it|understood|cool|great|awesome|perfect|nice|sure|right|all\s+good|sounds\s+good"
    r"|much\s+appreciated|no\s+problem"
    rf"|{_PRAISE_PATTERN_STR}"
    r"|bye|goodbye|cya|see\s+you(?:\s+later)?|farewell|have\s+a\s+good\s+(?:day|one)|exit|quit"
)
_PURE_CONVERSATIONAL = re.compile(
    rf"^\s*(?:(?:{_CONVERSATIONAL_PHRASES})[\s,!.?\-]*)+[\s!.?]*$",
    re.IGNORECASE,
)
_GREETING_PATTERN = re.compile(
    r"\b(?:hi|hello|hey|howdy|greetings|good\s+(?:morning|afternoon|evening|day)|hi\s+there|hey\s+there|hello\s+there|hiya|yo)\b",
    re.IGNORECASE,
)
_ACK_PATTERN = re.compile(
    r"\b(?:thanks|thank\s+you|thx|ok|okay|k|got\s+it|understood|cool|great|awesome|perfect|nice|sure|right|all\s+good|sounds\s+good|much\s+appreciated|no\s+problem)\b",
    re.IGNORECASE,
)
_PRAISE_PATTERN = re.compile(
    rf"\b(?:{_PRAISE_PATTERN_STR})\b",
    re.IGNORECASE,
)
_CLOSURE_PATTERN = re.compile(
    r"\b(?:bye|goodbye|cya|see\s+you|farewell|have\s+a\s+good\s+(?:day|one)|exit|quit)\b",
    re.IGNORECASE,
)
_PRAISE_AND_ACK_PRONOUNS = re.compile(
    rf"\b(?:{_PRAISE_PATTERN_STR}|got\s+it)\b",
    re.IGNORECASE,
)

# Anaphoric & coreference cues
_ANAPHORA = re.compile(
    r"\b(?:"
    r"it|its|that|this|these|those|them|the\s+same|the\s+above|the\s+previous|the\s+former|the\s+latter|earlier|from\s+before"
    r"|why\s+did\s+you|why\s+is\s+that|why\s+not|how\s+come|what\s+about|how\s+about|what\s+if|how\s+so"
    r"|optimize|refactor|rewrite|simplify|speed\s+up|clean\s+up"
    r"|instead|again|also|another\s+way|alternative|difference|better"
    r")\b",
    re.IGNORECASE,
)
_ELLIPTICAL = re.compile(
    r"^\s*(?:why|how|what\s+for|how\s+come)[\s?!.]*$",
    re.IGNORECASE,
)

# Short technical cues
_SHORT_TECHNICAL = re.compile(
    r"\b(?:"
    r"line\s+\d+"
    r"|(?:space|time|runtime|memory)\s+complexity"
    r"|big\s+o(?:\s+notation)?"
    r"|edge\s+cases?|type\s+hints?|unit\s+tests?"
    r"|memory\s+leak|stack\s+trace|null\s+pointer|off\s+by\s+one"
    r"|syntax\s+error|runtime\s+error|type\s+error|name\s+error|index\s+error|zero\s+division"
    r"|error\s+handling|exception\s+handling"
    r")\b"
    r"|\b(?:fix|debug|refactor)\s+(?:the\s+)?(?:bug|error|issue|code|snippet|function|method|query|script)\b",
    re.IGNORECASE,
)

ROLE_WEIGHTS = {
    "user": 1.0,
    "assistant": 0.2,
    "system": 0.0,
}
RECENCY_DECAY_LAMBDA = 0.6


@dataclass
class CurrentTurnScope:
    text: str
    words: list[str]
    word_count: float
    char_count: float
    has_code: bool
    has_math: bool
    asks_reasoning: bool
    asks_long_output: bool
    question_count: float
    is_pure_conversational: bool
    conversational_marker: str | None
    is_anaphoric: bool
    is_short_technical: bool


@dataclass
class HistoryScope:
    turn_count: int
    weighted_word_count: float
    prior_turn_has_code: bool
    prior_turn_has_math: bool
    prior_turn_asks_reasoning: bool
    history_has_code: bool
    history_asks_reasoning: bool


class FeatureDict(dict):
    """Subclass of dict preserving exact 10-feature mapping while attaching dual scopes."""

    def __init__(
        self,
        mapping: dict[str, float] | None = None,
        current_turn: CurrentTurnScope | None = None,
        history: HistoryScope | None = None,
        **kwargs: float,
    ) -> None:
        if mapping is not None:
            super().__init__(mapping, **kwargs)
        else:
            super().__init__(**kwargs)
        self.current_turn: CurrentTurnScope = current_turn  # type: ignore[assignment]
        self.history: HistoryScope = history  # type: ignore[assignment]

    def copy(self) -> "FeatureDict":
        return FeatureDict(
            super().copy(),
            current_turn=self.current_turn,
            history=self.history,
        )

    def __copy__(self) -> "FeatureDict":
        return self.copy()


def extract_dual_scope_features(messages: list[dict[str, str]]) -> FeatureDict:
    """Extract dual-scope features and legacy numeric vector in stable order."""
    # 1. Monolithic legacy features (100% backward compatible for learned router & DB)
    prompt = "\n".join(message.get("content") or "" for message in messages)
    words = prompt.split()
    prompt_chars = float(len(prompt))
    prompt_words = float(len(words))
    num_turns = float(len(messages))

    legacy_features = {
        "prompt_chars": prompt_chars,
        "prompt_words": prompt_words,
        "num_turns": num_turns,
        "has_code": float(bool(_CODE.search(prompt))),
        "has_math": float(bool(_MATH.search(prompt))),
        "question_count": float(prompt.count("?")),
        "asks_reasoning": float(bool(_REASONING.search(prompt))),
        "asks_long_output": float(bool(_LONG_OUTPUT.search(prompt))),
        "non_ascii_ratio": sum(ord(char) > 127 for char in prompt) / prompt_chars if prompt else 0.0,
        "avg_word_len": sum(len(word) for word in words) / prompt_words if words else 0.0,
    }

    # 2. Partition conversation into Current Turn vs History
    latest_user_idx = None
    for i in range(len(messages) - 1, -1, -1):
        if (messages[i].get("role") or "").strip().lower() == "user":
            latest_user_idx = i
            break

    if latest_user_idx is not None:
        curr_msg = messages[latest_user_idx]
        hist_msgs = messages[:latest_user_idx]
    elif messages:
        curr_msg = messages[-1]
        hist_msgs = messages[:-1]
    else:
        curr_msg = None
        hist_msgs = []

    # 3. Extract Current Turn Scope
    if curr_msg is not None:
        c_text = curr_msg.get("content") or ""
        c_words = c_text.split()
        c_has_code = bool(_CODE.search(c_text))
        c_has_math = bool(_MATH.search(c_text))
        c_asks_reasoning = bool(_REASONING.search(c_text))
        c_asks_long_output = bool(_LONG_OUTPUT.search(c_text))
        c_question_count = float(c_text.count("?"))

        is_pure_conv = bool(_PURE_CONVERSATIONAL.match(c_text)) and not (c_has_code or c_has_math)
        conv_marker: str | None = None
        if is_pure_conv:
            if _GREETING_PATTERN.search(c_text):
                conv_marker = "greeting"
            elif _PRAISE_PATTERN.search(c_text):
                conv_marker = "praise"
            elif _ACK_PATTERN.search(c_text):
                conv_marker = "acknowledgment"
            elif _CLOSURE_PATTERN.search(c_text):
                conv_marker = "closure"
            else:
                conv_marker = "conversational"

        if is_pure_conv:
            is_anaphoric = False
        else:
            c_text_no_praise = _PRAISE_AND_ACK_PRONOUNS.sub(" ", c_text)
            is_anaphoric = bool(_ANAPHORA.search(c_text_no_praise)) or bool(_ELLIPTICAL.match(c_text))

        is_short_tech = bool(_SHORT_TECHNICAL.search(c_text))

        current_turn = CurrentTurnScope(
            text=c_text,
            words=c_words,
            word_count=float(len(c_words)),
            char_count=float(len(c_text)),
            has_code=c_has_code,
            has_math=c_has_math,
            asks_reasoning=c_asks_reasoning,
            asks_long_output=c_asks_long_output,
            question_count=c_question_count,
            is_pure_conversational=is_pure_conv,
            conversational_marker=conv_marker,
            is_anaphoric=is_anaphoric,
            is_short_technical=is_short_tech,
        )
    else:
        current_turn = CurrentTurnScope(
            text="",
            words=[],
            word_count=0.0,
            char_count=0.0,
            has_code=False,
            has_math=False,
            asks_reasoning=False,
            asks_long_output=False,
            question_count=0.0,
            is_pure_conversational=False,
            conversational_marker=None,
            is_anaphoric=False,
            is_short_technical=False,
        )

    # 4. Extract Conversation History Scope
    hist_turn_count = len(hist_msgs)
    if hist_msgs:
        prior_content = hist_msgs[-1].get("content") or ""
        prior_code = bool(_CODE.search(prior_content))
        prior_math = bool(_MATH.search(prior_content))
        prior_reasoning = bool(_REASONING.search(prior_content))

        hist_code = prior_code or any(bool(_CODE.search(m.get("content") or "")) for m in hist_msgs[:-1])
        hist_reasoning = prior_reasoning or any(
            bool(_REASONING.search(m.get("content") or "")) for m in hist_msgs[:-1]
        )

        weighted_words = 0.0
        n_hist = len(hist_msgs)
        for i, m in enumerate(hist_msgs):
            d = n_hist - 1 - i
            role = (m.get("role") or "").strip().lower()
            w = ROLE_WEIGHTS.get(role, 1.0)
            cnt = len((m.get("content") or "").split())
            weighted_words += cnt * w * (RECENCY_DECAY_LAMBDA ** d)

        history = HistoryScope(
            turn_count=hist_turn_count,
            weighted_word_count=round(weighted_words, 4),
            prior_turn_has_code=prior_code,
            prior_turn_has_math=prior_math,
            prior_turn_asks_reasoning=prior_reasoning,
            history_has_code=hist_code,
            history_asks_reasoning=hist_reasoning,
        )
    else:
        history = HistoryScope(
            turn_count=0,
            weighted_word_count=0.0,
            prior_turn_has_code=False,
            prior_turn_has_math=False,
            prior_turn_asks_reasoning=False,
            history_has_code=False,
            history_asks_reasoning=False,
        )

    return FeatureDict(legacy_features, current_turn=current_turn, history=history)


def extract_features(messages: list[dict[str, str]]) -> FeatureDict:
    """Measure all message contents in a stable feature order while attaching dual-scope attributes."""
    return extract_dual_scope_features(messages)
