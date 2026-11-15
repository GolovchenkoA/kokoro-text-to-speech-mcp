"""Engine for Kokoro-82M (the ``kokoro`` package)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

import numpy as np

from tts_mcp.catalog import ModelSpec
from tts_mcp.devices import resolve_device

log = logging.getLogger(__name__)

DEFAULT_REPO = "hexgrad/Kokoro-82M"


class KokoroEngine:
    """One Kokoro pipeline per language, created lazily. Each line of text is one audio chunk."""

    def __init__(self, spec: ModelSpec, device: str | None) -> None:
        self._repo = str(spec.options.get("repo", DEFAULT_REPO))
        self._device = resolve_device(device or spec.device)
        self._pipelines: dict[str, object] = {}
        self._lock = threading.Lock()

    def _pipeline(self, lang_code: str):
        with self._lock:
            if lang_code not in self._pipelines:
                from kokoro import KPipeline  # heavy import: defer until first use

                log.info("Loading Kokoro pipeline for lang_code=%s on %s", lang_code, self._device)
                self._pipelines[lang_code] = KPipeline(lang_code=lang_code, repo_id=self._repo, device=self._device)
            return self._pipelines[lang_code]

    def synthesize(self, text: str, voice: str, language: str, speed: float) -> Iterator[np.ndarray]:
        pipeline = self._pipeline(language)
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
            if audio is None:
                continue
            chunk = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            yield np.ascontiguousarray(chunk, dtype=np.float32)
