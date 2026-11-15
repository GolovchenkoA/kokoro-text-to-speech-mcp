"""The contract every speech engine fulfils (the Strategy the rest of the server programs against)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Protocol

import importlib.util

import numpy as np

from tts_mcp.catalog import ModelSpec


class SpeechEngine(Protocol):
    """Turns text into audio with one model.

    An engine is a class that is built with its ``ModelSpec`` and the requested device
    (``MyEngine(spec, device)``), loads its model lazily on the first call, and yields mono
    float32 chunks at ``spec.sample_rate``. Small chunks keep pause and stop responsive. It must
    keep all audio in memory and must run on the CPU when no GPU is available.
    """

    def synthesize(self, text: str, voice: str, language: str, speed: float) -> Iterator[np.ndarray]:
        """Yield the audio of `text` as it is generated. `language` is the model's own language code."""
        ...

    def check_ready(self) -> None:
        """Raise `EngineUnavailable` (cheaply, without loading the model) if the model cannot run here.

        Called before a speech starts, so the caller gets the reason at once instead of a failure later.
        """
        ...


def is_installed(package: str) -> bool:
    """True if `package` can be imported (checked without importing it)."""
    try:
        return importlib.util.find_spec(package) is not None
    except (ImportError, ValueError):  # ValueError: an already imported module without a spec
        return True


EngineFactory = Callable[[ModelSpec, "str | None"], SpeechEngine]
