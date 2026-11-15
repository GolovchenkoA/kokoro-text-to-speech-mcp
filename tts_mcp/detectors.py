"""Language detectors: guess the language of a text. The guard asks one through a small protocol."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Detection:
    code: str  # ISO 639-1, lower case: "de", "pl"
    name: str  # English name: "German"
    confidence: float  # 0..1


class LanguageDetector(Protocol):
    def detect(self, text: str) -> Detection | None:
        """The most likely language of `text`, or None when there is no answer."""
        ...

    def warm_up(self) -> None:
        """Load whatever the first detection needs, so that it does not wait for it."""
        ...


class LinguaDetector:
    """Detects among all the languages Lingua knows, not only the ones a model speaks.

    That is deliberate: to say "Polish is not supported" the detector must know Polish. It runs offline
    on the CPU, and is created on first use because loading it takes a few seconds.
    """

    def __init__(self) -> None:
        self._detector = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._detector is None:
                from lingua import LanguageDetectorBuilder

                log.info("Loading the language detector")
                self._detector = LanguageDetectorBuilder.from_all_languages().build()
            return self._detector

    def warm_up(self) -> None:
        detector = self._load()
        detector.compute_language_confidence_values("Warming up the language detector.")

    def detect(self, text: str) -> Detection | None:
        values = self._load().compute_language_confidence_values(text)
        if not values:
            return None
        best = values[0]
        return Detection(
            code=best.language.iso_code_639_1.name.lower(), name=best.language.name.title(), confidence=best.value
        )


def lingua_is_installed() -> bool:
    try:
        import lingua  # noqa: F401
    except ImportError:
        return False
    return True
