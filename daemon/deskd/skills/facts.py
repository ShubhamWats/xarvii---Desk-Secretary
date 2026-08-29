"""Deterministic answers for questions that must never be hallucinated.

try_math and try_datetime return a ready-to-speak string, or None when the
utterance is not one of theirs. These run BEFORE the LLM.
"""

import ast
import operator
import re
from datetime import datetime, timedelta

_FILLER = re.compile(
    r"\b(please|can you|could you|tell me|what(?:'s| is| are)|how much is|"
    r"calculate|compute|equals?|equal to|the answer to|result of|me)\b",
    re.IGNORECASE,
)

_WORD_OPS = [
    (re.compile(r"\bmultiplied by\b|\btimes\b|\bx\b", re.I), "*"),
    (re.compile(r"\bdivided by\b|\bover\b", re.I), "/"),
    (re.compile(r"\bplus\b|\band\b(?=\s*[-+]?\d)|\badded (?:to|with)\b", re.I), "+"),
    (re.compile(r"\bminus\b|\bsubtract(ed)?( from)?\b|\bless\b", re.I), "-"),
    (re.compile(r"\bmodulo\b|\bmod\b|\bremainder of\b", re.I), "%"),
]

_NUM = r"-?\d+(?:\.\d+)?"
_EXPR_RE = re.compile(
    rf"(?:\(\s*)?{_NUM}(?:\s*[+\-*/%^()]|\s*(?:\*\*))\s*{_NUM}[\s\d+\-*/%().]*",
)
_PCT_OF = re.compile(rf"({_NUM})\s*%\s*of\s*({_NUM})", re.I)


class _SafeEval(ast.NodeVisitor):
    _BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod, ast.Pow: operator.pow}
    _UN = {ast.USub: operator.neg, ast.UAdd: operator.pos}

    def eval(self, node):
        if isinstance(node, ast.Expression):
            return self.eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._BIN:
            return self._BIN[type(node.op)](self.eval(node.left), self.eval(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._UN:
            return self._UN[type(node.op)](self.eval(node.operand))
        raise ValueError("unsupported expression")


def _fmt(value) -> str:
    if isinstance(value, float):
        if value == int(value):
            return str(int(value))
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _normalize_math_text(text: str) -> str:
    t = text
    m = _PCT_OF.search(t)
    if m:
        t = _PCT_OF.sub(lambda mm: f"({mm.group(1)} / 100 * {mm.group(2)})", t)
    for rx, sym in _WORD_OPS:
        t = rx.sub(sym, t)
    t = _FILLER.sub("", t)
    t = t.replace("?", "").replace(",", "").strip()
    return t


def try_math(text: str) -> str | None:
    """Return spoken answer for pure arithmetic utterances, else None."""
    if not re.search(r"\d", text):
        return None
    lowered = text.lower()
    looks_like_math = (
        "%" in text
        or re.search(r"(plus|minus|times|divided by|multiplied by|subtract|added to|x\b)", lowered)
        or re.search(rf"{_NUM}\s*[+\-*/^%]", lowered)
    )
    if not looks_like_math:
        return None
    expr = _normalize_math_text(text)
    m = _EXPR_RE.search(expr)
    if not m:
        return None
    candidate = m.group(0).strip().rstrip("+*/%^-.")
    try:
        tree = ast.parse(candidate, mode="eval")
        value = _SafeEval().eval(tree)
    except Exception:
        return None
    if isinstance(value, complex) or abs(value) > 1e15:
        return None
    return f"That comes to {_fmt(value)}."


def try_datetime(text: str, now: datetime | None = None) -> str | None:
    now = now or datetime.now()
    raw = re.sub(r"[?.!]", "", text.lower().replace("'s", "")).strip()

    if "tomorrow" in raw and len(raw) < 32:
        tmr = now + timedelta(days=1)
        return f"Tomorrow will be {tmr.strftime('%A, %B %-d')}."
    if "yesterday" in raw and len(raw) < 32:
        yst = now - timedelta(days=1)
        return f"Yesterday was {yst.strftime('%A, %B %-d')}."

    core = re.sub(r"\b(what|whats|which|is|it|the|current|right now|today|tell me|do you know|please|hey|hi|hello)\b", " ", raw)
    core = re.sub(r"\s+", " ", core).strip()
    if core in ("time",):
        return f"It's {now.strftime('%I:%M %p').lstrip('0').lower()}."
    if core in ("date", "todays date", "dates"):
        return f"Today is {now.strftime('%A, %B %-d %Y')}."
    if core in ("day",):
        return f"It's {now.strftime('%A')}."
    return None
