"""Unit tests of the models catalogue: reading models.json and choosing model, language and voice."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from tests.fakes import models_data
from tts_mcp.catalog import CatalogError, Selection, SelectionError, load_catalog, parse_catalog


@pytest.fixture(scope="module")
def catalog():
    return parse_catalog(models_data())


def model(**changes):
    raw = {
        "engine": "package.module:Engine",
        "sample_rate": 16000,
        "languages": {"en": {"voices": ["one", "two"]}},
    }
    raw.update(changes)
    return raw


def catalog_of(models, default="m"):
    return parse_catalog({"default_model": default, "models": models})


# -- the shipped file ----------------------------------------------------------------------------
def test_the_shipped_file_lists_both_models_and_a_default(catalog):
    assert catalog.default_model == "kokoro"
    assert set(catalog.models) == {"kokoro", "qwen3"}
    assert catalog.models["kokoro"].engine == "tts_mcp.engines.kokoro:KokoroEngine"
    assert catalog.models["qwen3"].sample_rate == 24000


def test_voices_shared_by_a_model_are_available_in_every_language(catalog):
    languages = catalog.models["qwen3"].languages
    assert all("Ryan" in lang.voices and "Sohee" in lang.voices for lang in languages.values())


# -- resolving a request -------------------------------------------------------------------------
def test_with_nothing_given_the_default_model_language_and_voice_are_used(catalog):
    assert catalog.resolve() == Selection("kokoro", "af_heart", "en-us")


def test_a_voice_selects_its_language_within_the_model(catalog):
    assert catalog.resolve(voice="ff_siwis") == Selection("kokoro", "ff_siwis", "fr")
    assert catalog.resolve(model="qwen3", voice="Ryan") == Selection("qwen3", "Ryan", "auto")


def test_only_the_default_model_is_used_unless_another_is_named(catalog):
    with pytest.raises(SelectionError, match="unknown voice 'Ryan' in model 'kokoro'"):
        catalog.resolve(voice="Ryan")  # qwen3 has it, but kokoro is the default model
    switched = replace(catalog, default_model="qwen3")
    assert switched.resolve() == Selection("qwen3", "Ryan", "auto")
    with pytest.raises(SelectionError, match="unknown voice 'af_heart' in model 'qwen3'"):
        switched.resolve(voice="af_heart")


def test_a_language_selects_its_default_voice_in_the_model(catalog):
    assert catalog.resolve(language="fr") == Selection("kokoro", "ff_siwis", "fr")
    assert catalog.resolve(model="qwen3", language="de") == Selection("qwen3", "Ryan", "de")
    assert catalog.resolve(model="qwen3", language="ko") == Selection("qwen3", "Sohee", "ko")
    with pytest.raises(SelectionError, match="language 'de' is not supported in model 'kokoro'"):
        catalog.resolve(language="de")  # the default model has no German


def test_a_short_language_code_matches_its_variants(catalog):
    assert catalog.resolve(language="en") == Selection("kokoro", "af_heart", "en-us")
    assert catalog.resolve(language="en-gb") == Selection("kokoro", "bf_emma", "en-gb")
    assert catalog.resolve(language="EN-GB") == Selection("kokoro", "bf_emma", "en-gb")


def test_a_model_can_be_named(catalog):
    assert catalog.resolve(model="qwen3") == Selection("qwen3", "Ryan", "auto")
    assert catalog.resolve(model="qwen3", language="en") == Selection("qwen3", "Ryan", "en")
    assert catalog.resolve(model="qwen3", voice="Vivian", language="zh") == Selection("qwen3", "Vivian", "zh")


def test_blank_values_count_as_not_given(catalog):
    assert catalog.resolve(model="  ", voice="", language=" ") == catalog.resolve()


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"model": "nope"}, "unknown model 'nope'"),
        ({"voice": "xx_nobody"}, "unknown voice 'xx_nobody'"),
        ({"language": "pl"}, "language 'pl' is not supported"),
        ({"voice": "af_heart", "language": "fr"}, "voice 'af_heart' is not available for language 'fr'"),
        ({"model": "kokoro", "voice": "Ryan"}, "unknown voice 'Ryan' in model 'kokoro'"),
        ({"model": "kokoro", "language": "de"}, "language 'de' is not supported in model 'kokoro'"),
    ],
)
def test_requests_that_match_nothing_are_rejected_with_a_reason(catalog, arguments, message):
    with pytest.raises(SelectionError, match=message) as error:
        catalog.resolve(**arguments)
    assert "list_models" in str(error.value)


def test_describe_lists_every_model_language_and_voice(catalog):
    described = catalog.describe()
    assert described["default_model"] == "kokoro"
    english = described["models"]["kokoro"]["languages"]["en-us"]
    assert english["name"] == "American English" and english["default_voice"] == "af_heart"
    assert "am_adam" in english["voices"]
    assert "Uncle_Fu" in described["models"]["qwen3"]["languages"]["de"]["voices"]
    json.dumps(described)  # plain data: it is returned by a tool


# -- validating the file -------------------------------------------------------------------------
def test_defaults_are_filled_in_for_optional_fields():
    spec = catalog_of({"m": model()}).models["m"]
    assert spec.name == "m" and spec.device == "auto" and dict(spec.options) == {}
    language = spec.languages["en"]
    assert (language.name, language.engine_code, language.default_voice) == ("en", "en", "one")


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "top level"),
        ({"default_model": "m"}, "'models' must be a non-empty object"),
        ({"default_model": "m", "models": {}}, "'models' must be a non-empty object"),
        ({"default_model": "x", "models": {"m": model()}}, "'default_model' must name one of the models: m"),
        ({"default_model": "m", "models": {"m": model(engine="nocolon")}}, "'engine' must be an import path"),
        ({"default_model": "m", "models": {"m": model(engine="a:b:c")}}, "'engine' must be an import path"),
        ({"default_model": "m", "models": {"m": model(sample_rate=0)}}, "'sample_rate' must be a positive integer"),
        ({"default_model": "m", "models": {"m": model(sample_rate="fast")}}, "'sample_rate'"),
        ({"default_model": "m", "models": {"m": model(languages={})}}, "'languages' must be a non-empty object"),
        ({"default_model": "m", "models": {"m": model(languages={"en": {}})}}, "language 'en' has no voices"),
        (
            {"default_model": "m", "models": {"m": model(languages={"en": {"voices": ["a"], "default_voice": "b"}})}},
            "'default_voice' 'b' is not one of its voices",
        ),
        ({"default_model": "m", "models": {"m": model(options=[])}}, "'options' must be an object"),
        ({"default_model": "m", "models": {"m": "text"}}, "model 'm' must be an object"),
    ],
)
def test_an_invalid_file_is_rejected_with_a_message_that_names_the_problem(data, message):
    with pytest.raises(CatalogError, match=message):
        parse_catalog(data)


def test_a_missing_file_is_reported_with_its_path(tmp_path):
    with pytest.raises(CatalogError, match="cannot read the models file"):
        load_catalog(tmp_path / "missing.json")


def test_a_file_that_is_not_json_is_reported_with_its_path(tmp_path):
    path = tmp_path / "models.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(CatalogError, match="is not valid JSON") as error:
        load_catalog(path)
    assert str(path) in str(error.value)


def test_problems_in_a_file_name_the_file(tmp_path):
    path = tmp_path / "models.json"
    path.write_text(json.dumps({"models": {}}), encoding="utf-8")
    with pytest.raises(CatalogError) as error:
        load_catalog(path)
    assert str(path) in str(error.value)
