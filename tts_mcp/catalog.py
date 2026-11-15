"""The catalogue of text-to-speech models, read from the models file (``models.json``).

Which models exist, which languages and voices each one has, which model is the default and which
voice is the default for a model and language all live in that file. No code names a model: a model
is replaced, added or made the default by editing the file only. The engine that runs a model is
named in the file too, by its import path (see ``tts_mcp.engines``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tts_mcp.errors import InvalidSpeechRequest


class CatalogError(ValueError):
    """The models file is missing or invalid."""


class SelectionError(InvalidSpeechRequest):
    """No model, language and voice match a speech request."""


@dataclass(frozen=True)
class Language:
    """A language a model speaks, with the voices that can be used for it."""

    code: str  # the catalogue's own code, e.g. "en-us", "de"
    name: str
    engine_code: str  # what the engine calls this language
    default_voice: str
    voices: tuple[str, ...]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    engine: str  # "package.module:ClassName"
    sample_rate: int  # Hz of the audio the engine yields
    device: str  # "auto", "cpu", "cuda" or "mps"; falls back to the CPU when unavailable
    languages: Mapping[str, Language]  # in file order; the first one is the model's default language
    options: Mapping[str, Any] = field(default_factory=dict)  # free-form, passed to the engine


@dataclass(frozen=True)
class Selection:
    """The outcome of resolving a request: exactly one model, language and voice."""

    model: str
    voice: str
    language: str


def _matches(code: str, wanted: str) -> bool:
    """`en` matches `en`, `en-us` and `en-gb`; `en-us` matches only itself."""
    wanted = wanted.lower()
    return code == wanted or code.startswith(wanted + "-")


@dataclass(frozen=True)
class Catalog:
    default_model: str
    models: Mapping[str, ModelSpec]

    def resolve(self, model: str | None = None, voice: str | None = None, language: str | None = None) -> Selection:
        """Pick the model, language and voice for a request. Anything left out is chosen from the file.

        Without `model`, the default model is tried first, then the others in file order, and the
        first one that has the voice and the language wins. Without `voice`, the language's default
        voice is used. With neither voice nor language, the model's first language is used.
        """
        model, voice, language = (value.strip() or None if value else None for value in (model, voice, language))
        if model:
            if model not in self.models:
                raise SelectionError(f"unknown model '{model}'. Call list_models for valid names.")
            candidates = [self.models[model]]
        else:
            candidates = [self.models[self.default_model]]
            candidates += [spec for spec in self.models.values() if spec.id != self.default_model]

        for spec in candidates:
            selection = self._pick(spec, voice, language)
            if selection is not None:
                return selection
        raise SelectionError(self._explain(candidates, voice, language))

    @staticmethod
    def _pick(spec: ModelSpec, voice: str | None, language: str | None) -> Selection | None:
        languages = [lang for lang in spec.languages.values() if not language or _matches(lang.code, language)]
        if voice:
            languages = [lang for lang in languages if voice in lang.voices]
        if not languages:
            return None
        chosen = languages[0]
        return Selection(spec.id, voice or chosen.default_voice, chosen.code)

    @staticmethod
    def _explain(candidates: list[ModelSpec], voice: str | None, language: str | None) -> str:
        scope = f" in model '{candidates[0].id}'" if len(candidates) == 1 else ""
        hint = " Call list_models for what is available."
        languages = [lang for spec in candidates for lang in spec.languages.values()]
        if voice and not any(voice in lang.voices for lang in languages):
            return f"unknown voice '{voice}'{scope}.{hint}"
        if language and not any(_matches(lang.code, language) for lang in languages):
            return f"language '{language}' is not supported{scope}.{hint}"
        return f"voice '{voice}' is not available for language '{language}'{scope}.{hint}"

    def describe(self) -> dict[str, Any]:
        """The catalogue as plain data (what the list_models tool returns)."""
        return {
            "default_model": self.default_model,
            "models": {
                spec.id: {
                    "name": spec.name,
                    "languages": {
                        lang.code: {"name": lang.name, "default_voice": lang.default_voice, "voices": list(lang.voices)}
                        for lang in spec.languages.values()
                    },
                }
                for spec in self.models.values()
            },
        }


def default_models_file() -> Path:
    """The ``models.json`` that ships next to the package."""
    return Path(__file__).resolve().parent.parent / "models.json"


def load_catalog(path: Path) -> Catalog:
    """Read and validate the models file. Raises CatalogError with a message that names the problem."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CatalogError(f"cannot read the models file {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise CatalogError(f"the models file {path} is not valid JSON: {exc}") from exc
    try:
        return parse_catalog(data)
    except CatalogError as exc:
        raise CatalogError(f"{path}: {exc}") from exc


def parse_catalog(data: Any) -> Catalog:
    if not isinstance(data, dict):
        raise CatalogError("the top level must be an object")
    raw_models = data.get("models")
    if not isinstance(raw_models, dict) or not raw_models:
        raise CatalogError("'models' must be a non-empty object")
    models = {model_id: _parse_model(model_id, raw) for model_id, raw in raw_models.items()}
    default = data.get("default_model")
    if default not in models:
        raise CatalogError(f"'default_model' must name one of the models: {', '.join(models)}")
    return Catalog(default_model=default, models=models)


def _parse_model(model_id: str, raw: Any) -> ModelSpec:
    where = f"model '{model_id}'"
    if not isinstance(raw, dict):
        raise CatalogError(f"{where} must be an object")
    engine = raw.get("engine")
    if not isinstance(engine, str) or engine.count(":") != 1 or not all(engine.split(":")):
        raise CatalogError(f"{where}: 'engine' must be an import path like 'package.module:ClassName'")
    sample_rate = raw.get("sample_rate")
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
        raise CatalogError(f"{where}: 'sample_rate' must be a positive integer")
    raw_languages = raw.get("languages")
    if not isinstance(raw_languages, dict) or not raw_languages:
        raise CatalogError(f"{where}: 'languages' must be a non-empty object")
    shared_voices = _voices(raw.get("voices", []), f"{where}: 'voices'")
    languages: dict[str, Language] = {}
    for code, raw_language in raw_languages.items():
        languages[code.lower()] = _parse_language(code.lower(), raw_language, shared_voices, where)
    options = raw.get("options", {})
    if not isinstance(options, dict):
        raise CatalogError(f"{where}: 'options' must be an object")
    return ModelSpec(
        id=model_id,
        name=str(raw.get("name", model_id)),
        engine=engine,
        sample_rate=sample_rate,
        device=str(raw.get("device", "auto")),
        languages=languages,
        options=options,
    )


def _parse_language(code: str, raw: Any, shared_voices: tuple[str, ...], where: str) -> Language:
    here = f"{where}, language '{code}'"
    if not isinstance(raw, dict):
        raise CatalogError(f"{here} must be an object")
    voices = _voices(raw["voices"], f"{here}: 'voices'") if "voices" in raw else shared_voices
    if not voices:
        raise CatalogError(f"{here} has no voices (list them here or in the model's 'voices')")
    default_voice = raw.get("default_voice", voices[0])
    if default_voice not in voices:
        raise CatalogError(f"{here}: 'default_voice' '{default_voice}' is not one of its voices")
    return Language(
        code=code,
        name=str(raw.get("name", code)),
        engine_code=str(raw.get("engine_code", code)),
        default_voice=default_voice,
        voices=voices,
    )


def _voices(raw: Any, where: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or not all(isinstance(voice, str) and voice for voice in raw):
        raise CatalogError(f"{where} must be a list of voice names")
    return tuple(raw)
