"""Guards that check a speech request before it reaches the speech backend.

`GuardedSpeech` wraps the backend and runs its guards on `start()` only (the other calls pass straight
through; a guard can be added to them later). A guard returns the request, possibly adjusted, or raises
`InvalidSpeechRequest`, which the tool shows to the agent as an error. The tools and the backend know
nothing about guards.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Protocol

from tts_mcp.catalog import Catalog, ModelSpec, SelectionError, language_matches
from tts_mcp.detectors import LanguageDetector
from tts_mcp.speech import SpeechController

log = logging.getLogger(__name__)

MIN_CHARS = 120  # a shorter text is not checked and counts as supported
SAMPLE_CHARS = 200  # only the beginning of a longer text is looked at, to keep the check fast
MIN_CONFIDENCE = 0.8  # a less certain answer from the detector counts as supported


@dataclass(frozen=True)
class SpeechRequest:
    text: str
    voice: str | None
    speed: float
    model: str | None = None
    language: str | None = None


class Guard(Protocol):
    def check(self, request: SpeechRequest) -> SpeechRequest:
        """Return the request (possibly adjusted) or raise InvalidSpeechRequest."""
        ...


class LanguageGuard:
    """Refuses a text whose language the model does not speak, or that the chosen voice cannot read.

    "The model" is the one the request names, otherwise the default model of the models file.

    Only the first `SAMPLE_CHARS` characters are examined, and nothing at all when the text has fewer than
    `MIN_CHARS`. When the caller named no language, voice or model, the detected language is passed on so
    that a model that speaks it is chosen.
    """

    def __init__(
        self,
        catalog: Catalog,
        detector: LanguageDetector,
        min_chars: int = MIN_CHARS,
        sample_chars: int = SAMPLE_CHARS,
        min_confidence: float = MIN_CONFIDENCE,
    ) -> None:
        self._catalog = catalog
        self._detector = detector
        self._min_chars = min_chars
        self._sample_chars = sample_chars
        self._min_confidence = min_confidence

    def check(self, request: SpeechRequest) -> SpeechRequest:
        text = request.text.strip()
        if len(text) < self._min_chars:
            return request  # too short to tell: counts as supported

        detection = self._detector.detect(text[: self._sample_chars])
        if detection is None or detection.confidence < self._min_confidence:
            return request  # not sure: counts as supported

        spec = self._catalog.model_for(request.model)
        if spec is None:
            return request  # an unknown model: the catalogue reports it when the request is resolved
        if not self._is_spoken_by(spec, detection.code):
            raise SelectionError(
                f"The text language was detected as {detection.name} ({detection.code}) and it is not "
                f"supported by the model. Supported languages: {self._supported_languages(spec)}."
            )
        if not (request.language or request.voice):
            return replace(request, language=detection.code)

        # The caller chose a language or a voice: it must be able to read the detected language.
        selection = self._catalog.resolve(request.model, request.voice, request.language)
        chosen = self._catalog.models[selection.model].languages[selection.language]
        if chosen.detects_language or language_matches(chosen.code, detection.code):
            return request
        raise SelectionError(
            f"The text is in {detection.name} ({detection.code}) but {chosen.name} (voice '{selection.voice}', "
            f"model '{selection.model}') was chosen. Pass language '{detection.code}' or leave the voice out."
        )

    @staticmethod
    def _is_spoken_by(spec: ModelSpec, code: str) -> bool:
        return any(
            language_matches(language.code, code) for language in spec.languages.values() if not language.detects_language
        )

    @staticmethod
    def _supported_languages(spec: ModelSpec) -> str:
        return ", ".join(language.name for language in spec.languages.values() if not language.detects_language)


class GuardedSpeech:
    """A `SpeechController` that runs the guards on `start()` and passes every other call through."""

    def __init__(self, inner: SpeechController, guards: Sequence[Guard]) -> None:
        self._inner = inner
        self._guards = tuple(guards)

    def start(
        self, text: str, voice: str | None, speed: float, model: str | None = None, language: str | None = None
    ) -> dict:
        request = SpeechRequest(text, voice, speed, model, language)
        for guard in self._guards:
            request = guard.check(request)
        return self._inner.start(request.text, request.voice, request.speed, request.model, request.language)

    def pause(self) -> bool:
        return self._inner.pause()

    def resume(self) -> bool:
        return self._inner.resume()

    def stop(self) -> bool:
        return self._inner.stop()

    def describe(self) -> str:
        return self._inner.describe()

    def state_label(self) -> str:
        return self._inner.state_label()

    def shutdown(self) -> None:
        self._inner.shutdown()
