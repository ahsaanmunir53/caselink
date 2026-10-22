"""Small text helpers."""

import re
import unicodedata

CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "һ": "h", "ԁ": "d", "ӏ": "l", "ԛ": "q", "ԝ": "w",
})
_URDU = re.compile(r"[\u0600-\u06FF]")


def fold_confusables(text: str) -> str:
    return text.translate(CONFUSABLES)


def detect_language(text: str) -> str:
    """'ur' for Urdu script, 'roman' for Roman Urdu, 'en' otherwise."""
    if len(_URDU.findall(text)) > 8:
        return "ur"
    words = set(re.findall(r"[a-z]+", text.lower()))
    roman = {"ka", "ki", "ke", "ne", "se", "mein", "hai", "hain", "nahi", "aur", "par", "ko", "walon", "liye", "bhej",
             "paise", "naukri", "kar", "diye", "gaye", "aya", "bola", "mujhe", "humne", "hoon", "band"}
    return "roman" if len(words & roman) >= 3 else "en"


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
