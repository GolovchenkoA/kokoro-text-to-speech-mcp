"""Spoken replies for voice commands."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from tts_mcp.audio import play_blocking
from tts_mcp.synthesis import SpeechSynthesizer

ANNOUNCE_LANGUAGE = "en"  # status is always announced in English, by the first model that speaks it


class StatusAnnouncer:
    """Speaks a short message on its own stream, independent of the current speech."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        play: Callable[[np.ndarray, int], None] = play_blocking,
    ) -> None:
        self._synthesizer = synthesizer
        self._play = play

    def announce(self, message: str) -> None:
        selection = self._synthesizer.catalog.resolve(language=ANNOUNCE_LANGUAGE)
        chunks = list(self._synthesizer.synthesize(message, selection, 1.0))
        if chunks:
            self._play(np.concatenate(chunks), self._synthesizer.sample_rate(selection.model))
