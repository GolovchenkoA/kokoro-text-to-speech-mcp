"""Text-to-speech synthesis with Kokoro."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

import numpy as np

from kokoro_mcp.voices import language_code

log = logging.getLogger(__name__)

REPO_ID = "hexgrad/Kokoro-82M"


class SpeechSynthesizer:
    """Turns text into audio chunks. Owns the Kokoro pipelines (one per language, created lazily)."""

    def __init__(self, device: str | None = None) -> None:
        self._device = device
        self._pipelines: dict[str, object] = {}
        self._lock = threading.Lock()

    def _pipeline(self, lang_code: str):
        with self._lock:
            if lang_code not in self._pipelines:
                from kokoro import KPipeline  # heavy import: defer until first use

                log.info("Loading Kokoro pipeline for lang_code=%s", lang_code)
                kwargs = {"lang_code": lang_code, "repo_id": REPO_ID}
                if self._device:
                    kwargs["device"] = self._device
                self._pipelines[lang_code] = KPipeline(**kwargs)
            return self._pipelines[lang_code]

    def synthesize(self, text: str, voice: str, speed: float) -> Iterator[np.ndarray]:
        """Yield float32 mono chunks (one per line of text) as they are generated."""
        lang_code = language_code(voice)
        if lang_code is None:
            raise ValueError(f"unknown voice '{voice}'")
        pipeline = self._pipeline(lang_code)
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
            if audio is None:
                continue
            chunk = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            yield np.ascontiguousarray(chunk, dtype=np.float32)
