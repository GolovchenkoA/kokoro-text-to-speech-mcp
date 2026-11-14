"""Spoken replies for voice commands."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from kokoro_mcp.audio import play_blocking
from kokoro_mcp.synthesis import SpeechSynthesizer

ANNOUNCE_VOICE = "af_heart"  # always English


class StatusAnnouncer:
    """Speaks a short message on its own stream, independent of the current speech."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        play: Callable[[np.ndarray], None] = play_blocking,
    ) -> None:
        self._synthesizer = synthesizer
        self._play = play

    def announce(self, message: str) -> None:
        chunks = list(self._synthesizer.synthesize(message, ANNOUNCE_VOICE, 1.0))
        if chunks:
            self._play(np.concatenate(chunks))
