"""Splitting text for models that generate a whole utterance at once."""

from __future__ import annotations

import re

_SENTENCE_END = re.compile(r"(?<=[.!?。！？…])\s+")


def split_text(text: str, max_chars: int) -> list[str]:
    """Split text into pieces of at most `max_chars`, at line breaks, sentence ends or spaces.

    Short pieces let playback start early and keep pause and stop responsive when the model cannot
    stream. Pieces are returned in order, without empty ones.
    """
    sentences: list[str] = []
    for line in text.splitlines():
        sentences.extend(part.strip() for part in _SENTENCE_END.split(line) if part.strip())

    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        for part in _hard_split(sentence, max_chars):
            if current and len(current) + 1 + len(part) > max_chars:
                pieces.append(current)
                current = part
            else:
                current = f"{current} {part}" if current else part
    if current:
        pieces.append(current)
    return pieces


def _hard_split(sentence: str, max_chars: int) -> list[str]:
    """Cut a sentence that is longer than `max_chars`, at a space when there is one."""
    parts = []
    while len(sentence) > max_chars:
        cut = sentence.rfind(" ", 0, max_chars)
        cut = cut if cut > 0 else max_chars
        parts.append(sentence[:cut].strip())
        sentence = sentence[cut:].strip()
    if sentence:
        parts.append(sentence)
    return parts
