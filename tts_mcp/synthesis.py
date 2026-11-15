"""Text-to-speech synthesis: routes a request to the engine of the selected model.

This module knows no model. The catalogue says which engine class runs which model and the
factory builds it, so replacing or adding a model is a change to the models file only.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

import numpy as np

from tts_mcp.catalog import Catalog, Selection
from tts_mcp.engines import EngineFactory, SpeechEngine, create_engine

log = logging.getLogger(__name__)


class SpeechSynthesizer:
    """Turns text into audio chunks. Engines are created lazily, one per model, and kept."""

    def __init__(self, catalog: Catalog, device: str | None = None, factory: EngineFactory = create_engine) -> None:
        self.catalog = catalog
        self._device = device
        self._factory = factory
        self._engines: dict[str, SpeechEngine] = {}
        self._lock = threading.Lock()

    def sample_rate(self, model: str) -> int:
        """Sample rate of a model's audio. Read from the catalogue, so no model has to be loaded."""
        return self.catalog.models[model].sample_rate

    def _engine(self, model: str) -> SpeechEngine:
        with self._lock:
            if model not in self._engines:
                log.info("Creating the engine for model '%s'", model)
                self._engines[model] = self._factory(self.catalog.models[model], self._device)
            return self._engines[model]

    def synthesize(self, text: str, selection: Selection, speed: float) -> Iterator[np.ndarray]:
        """Yield float32 mono chunks as they are generated, at `sample_rate(selection.model)`."""
        spec = self.catalog.models[selection.model]
        language = spec.languages[selection.language].engine_code
        yield from self._engine(selection.model).synthesize(text, selection.voice, language, speed)
