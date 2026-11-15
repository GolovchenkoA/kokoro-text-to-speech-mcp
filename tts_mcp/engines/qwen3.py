"""Engine for Qwen3-TTS (the ``qwen-tts`` package): preset voices only, no voice cloning."""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

import numpy as np

from tts_mcp.catalog import ModelSpec
from tts_mcp.devices import resolve_device
from tts_mcp.engines.base import install_hint, is_installed
from tts_mcp.engines.text import split_text
from tts_mcp.errors import EngineUnavailable

log = logging.getLogger(__name__)

DEFAULT_REPO = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_MAX_CHARS = 300


class Qwen3Engine:
    """Runs a Qwen3-TTS CustomVoice model on the GPU when there is one and on the CPU otherwise.

    The package returns a whole waveform per call, so the text is cut into short pieces and one
    piece is generated at a time. The model has no speed control; ``speed`` is ignored.
    """

    def __init__(self, spec: ModelSpec, device: str | None) -> None:
        self._repo = str(spec.options.get("repo", DEFAULT_REPO))
        self._max_chars = int(spec.options.get("max_chars", DEFAULT_MAX_CHARS))
        self._sample_rate = spec.sample_rate
        self._device = resolve_device(device or spec.device)
        self._model = None
        self._lock = threading.Lock()

    def check_ready(self) -> None:
        if not (is_installed("qwen_tts") and is_installed("torch")):
            raise EngineUnavailable(
                f"The Qwen3-TTS model is not installed. {install_hint('requirements-qwen3.txt')}"
            )

    def _load(self):
        with self._lock:
            if self._model is None:
                self._model = self._load_model()
            return self._model

    def _load_model(self):
        try:
            import torch  # imported here: it is a dependency of qwen-tts
            from qwen_tts import Qwen3TTSModel
        except ImportError as exc:
            raise RuntimeError(
                f"The Qwen3-TTS model is not installed. {install_hint('requirements-qwen3.txt')}"
            ) from exc

        if self._device != "cpu":
            try:
                log.info("Loading Qwen3-TTS %s on %s", self._repo, self._device)
                device_map = "cuda:0" if self._device == "cuda" else self._device
                return Qwen3TTSModel.from_pretrained(self._repo, device_map=device_map, dtype=torch.bfloat16)
            except Exception:  # driver or memory problems must not leave the user without speech
                log.exception("Could not load Qwen3-TTS on %s, falling back to the CPU", self._device)
                self._device = "cpu"
        log.info("Loading Qwen3-TTS %s on the CPU", self._repo)
        return Qwen3TTSModel.from_pretrained(self._repo, device_map="cpu", dtype=torch.float32)

    def synthesize(self, text: str, voice: str, language: str, speed: float) -> Iterator[np.ndarray]:
        model = self._load()
        for piece in split_text(text, self._max_chars):
            waveforms, rate = model.generate_custom_voice(text=piece, language=language, speaker=voice)
            audio = np.ascontiguousarray(np.asarray(waveforms[0], dtype=np.float32).reshape(-1))
            yield self._at_model_rate(audio, int(rate))

    def _at_model_rate(self, audio: np.ndarray, rate: int) -> np.ndarray:
        """Resample (linear) when the model's real rate differs from the rate in the models file."""
        if rate == self._sample_rate or len(audio) == 0:
            return audio
        target = max(1, round(len(audio) * self._sample_rate / rate))
        resampled = np.interp(np.linspace(0, len(audio) - 1, target), np.arange(len(audio)), audio)
        return resampled.astype(np.float32)
