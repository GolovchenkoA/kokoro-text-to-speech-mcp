"""Voice activity detection: a cheap gate in front of the speech recognizer."""

from __future__ import annotations

import collections

import numpy as np

from kokoro_mcp.config import Settings

VAD_PREROLL_BLOCKS = 3  # 300 ms of audio kept before speech starts
VAD_HANGOVER_BLOCKS = 5  # 500 ms of silence tolerated before an utterance is closed


class EnergyGate:
    """Decides per 100 ms block whether anyone is speaking, so the heavier recognizer only runs on
    speech. Keeps a short pre-roll (so the first syllable is not cut) and a hangover (so the end of
    a phrase is not cut)."""

    def __init__(self, threshold: float) -> None:
        self.threshold = threshold
        self._preroll: collections.deque[bytes] = collections.deque(maxlen=VAD_PREROLL_BLOCKS)
        self._open = False
        self._quiet = 0

    def _is_loud(self, block: bytes) -> bool:
        samples = np.frombuffer(block, dtype=np.int16).astype(np.float32)
        return samples.size > 0 and float(np.sqrt(np.mean(samples * samples))) >= self.threshold

    def process(self, block: bytes) -> tuple[list[bytes], bool]:
        """Return (blocks to feed the recognizer, whether the utterance just ended)."""
        loud = self._is_loud(block)
        if not self._open:
            if not loud:
                self._preroll.append(block)
                return [], False
            self._open, self._quiet = True, 0
            feed = [*self._preroll, block]
            self._preroll.clear()
            return feed, False
        if loud:
            self._quiet = 0
            return [block], False
        self._quiet += 1
        if self._quiet >= VAD_HANGOVER_BLOCKS:
            self._open = False
            return [block], True
        return [block], False


def make_gate(settings: Settings) -> EnergyGate | None:
    """The gate configured by KOKORO_VAD / KOKORO_VAD_THRESHOLD, or None when the gate is off."""
    if settings.vad_mode == "off":
        return None
    return EnergyGate(settings.vad_threshold)
