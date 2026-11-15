"""Creates the engine a model names in the models file (Factory by import path: no code lists models)."""

from __future__ import annotations

import importlib

from tts_mcp.catalog import CatalogError, ModelSpec
from tts_mcp.engines.base import SpeechEngine


def create_engine(spec: ModelSpec, device: str | None) -> SpeechEngine:
    """Import the class named by ``spec.engine`` ("package.module:ClassName") and build it.

    The models file is the user's own configuration, so what it names is imported. Adding a model
    with an existing engine class needs no code; a new model family needs one new engine class.
    """
    module_name, _, class_name = spec.engine.partition(":")
    try:
        engine_class = getattr(importlib.import_module(module_name), class_name)
    except (ImportError, AttributeError) as exc:
        raise CatalogError(f"model '{spec.id}': cannot load engine '{spec.engine}': {exc}") from exc
    return engine_class(spec, device)
