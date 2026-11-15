"""Spoken replies for voice commands."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from tts_mcp.audio import play_blocking
from tts_mcp.catalog import SelectionError, Selection
from tts_mcp.synthesis import SpeechSynthesizer

ANNOUNCE_LANGUAGE = "en"  # status is always announced in English: by the default model, else the first that speaks it


class StatusAnnouncer:
    """Speaks a short message on its own stream, independent of the current speech."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        play: Callable[[np.ndarray, int], None] = play_blocking,
    ) -> None:
        self._synthesizer = synthesizer
        self._play = play

    def _english_selection(self) -> Selection:
        catalog = self._synthesizer.catalog
        for model in (None, *catalog.models):  # None: the default model
            try:
                return catalog.resolve(model, None, ANNOUNCE_LANGUAGE)
            except SelectionError:
                continue
        return catalog.resolve(None, None, ANNOUNCE_LANGUAGE)  # raises: no model speaks English

    def announce(self, message: str) -> None:
        selection = self._english_selection()
        chunks = list(self._synthesizer.synthesize(message, selection, 1.0))
        if chunks:
            self._play(np.concatenate(chunks), self._synthesizer.sample_rate(selection.model))
