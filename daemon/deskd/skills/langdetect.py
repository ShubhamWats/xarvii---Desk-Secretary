"""Language detection (script-based) for en/hi multilingual replies."""

import re

_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def detect_lang(text: str) -> str:
    """'hi' if Devanagari chars dominate, else 'en'."""
    dev = len(_DEVANAGARI.findall(text))
    letters = len(re.findall(r"[A-Za-z]", text)) + dev
    if letters == 0:
        return "en"
    return "hi" if dev > letters * 0.3 else "en"


VOICE_FOR_LANG = {
    "en": "edge:en-IN-NeerjaNeural",
    "hi": "edge:hi-IN-SwaraNeural",
}


def reply_language_directive(lang: str) -> str:
    if lang == "hi":
        return "The user is speaking Hindi. Reply ONLY in Hindi (Devanagari script)."
    return "Reply in English."
