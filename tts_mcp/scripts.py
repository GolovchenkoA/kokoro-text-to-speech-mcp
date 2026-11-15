"""Guessing which languages a text can be in from its writing system.

A Latin text can be in dozens of languages, so nothing is guessed for it. A text in another writing
system narrows it down: Cyrillic is Russian, Ukrainian and so on, Hangul is Korean. The server uses
this to refuse a voice that cannot read the text, and to pick a model that can.
"""

from __future__ import annotations

# (name, first, last) code point ranges of the letters of each writing system.
_RANGES: tuple[tuple[str, int, int], ...] = (
    ("Cyrillic", 0x0400, 0x052F),
    ("Greek", 0x0370, 0x03FF),
    ("Hebrew", 0x0590, 0x05FF),
    ("Arabic", 0x0600, 0x06FF),
    ("Devanagari", 0x0900, 0x097F),
    ("Thai", 0x0E00, 0x0E7F),
    ("Hangul", 0xAC00, 0xD7AF),
    ("Hangul", 0x1100, 0x11FF),
    ("Kana", 0x3040, 0x30FF),
    ("Han", 0x4E00, 0x9FFF),
)

# Language codes (the catalogue's, in order of likelihood) for each writing system.
_LANGUAGES: dict[str, tuple[str, ...]] = {
    "Cyrillic": ("ru", "uk", "bg", "sr", "be", "mk", "kk"),
    "Greek": ("el",),
    "Hebrew": ("he",),
    "Arabic": ("ar", "fa", "ur"),
    "Devanagari": ("hi", "mr", "ne"),
    "Thai": ("th",),
    "Hangul": ("ko",),
    "Kana": ("ja",),
    "Han": ("zh", "ja"),
}

MIN_SHARE = 0.5  # the writing system must make up at least this share of the letters


def detect_script(text: str) -> str | None:
    """Name of the non-Latin writing system most of the text is written in, or None."""
    counts: dict[str, int] = {}
    letters = 0
    for char in text:
        if not char.isalpha():
            continue
        letters += 1
        code = ord(char)
        for name, first, last in _RANGES:
            if first <= code <= last:
                counts[name] = counts.get(name, 0) + 1
                break
    if not letters:
        return None
    # Japanese mixes kana with Han (kanji): the kana decide.
    if counts.get("Kana") and (counts.get("Kana", 0) + counts.get("Han", 0)) / letters >= MIN_SHARE:
        return "Kana"
    name, count = max(counts.items(), key=lambda item: item[1], default=("", 0))
    return name if count / letters >= MIN_SHARE else None


def candidate_languages(script: str) -> tuple[str, ...]:
    return _LANGUAGES.get(script, ())
