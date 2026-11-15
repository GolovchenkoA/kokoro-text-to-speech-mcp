"""Texts in a non-Latin writing system: the server picks a model that can read them or refuses."""

from __future__ import annotations

from dataclasses import replace

import pytest

from tests.conftest import call_tool_on
from tests.fakes import wait_until
from tests.fakes import models_data
from tts_mcp.catalog import Selection, SelectionError, parse_catalog
from tts_mcp.scripts import candidate_languages, detect_script

RUSSIAN = "Привет, это короткий тест речи."


@pytest.fixture(scope="module")
def catalog():
    return parse_catalog(models_data())


# -- detecting the writing system ----------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "script"),
    [
        (RUSSIAN, "Cyrillic"),
        ("Привет, world", "Cyrillic"),  # most letters are Cyrillic
        ("你好，这是一个测试。", "Han"),
        ("これは日本語のテストです。漢字も含みます。", "Kana"),  # kana decide: Japanese mixes them with kanji
        ("안녕하세요, 테스트입니다.", "Hangul"),
        ("नमस्ते, यह एक परीक्षण है।", "Devanagari"),
        ("Γεια σου κόσμε", "Greek"),
        ("مرحبا بالعالم", "Arabic"),
    ],
)
def test_the_writing_system_is_detected(text, script):
    assert detect_script(text) == script


@pytest.mark.parametrize(
    "text",
    ["Hello world", "Guten Tag, wie geht es dir?", "Привет, this is mostly English text here", "12345 !?", "", "   "],
)
def test_latin_or_mixed_or_empty_text_is_not_guessed(text):
    assert detect_script(text) is None


def test_each_script_has_candidate_languages_in_order_of_likelihood():
    assert candidate_languages("Cyrillic")[0] == "ru"
    assert candidate_languages("Han") == ("zh", "ja")
    assert candidate_languages("Kana") == ("ja",)
    assert candidate_languages("Nothing") == ()


# -- choosing a model for the text ---------------------------------------------------------------
def test_a_russian_text_is_not_supported_by_the_default_model(catalog):
    with pytest.raises(SelectionError, match="model 'kokoro' has no language for it"):
        catalog.resolve(text=RUSSIAN)  # kokoro is the default and has no Cyrillic language
    assert catalog.resolve(model="qwen3", text=RUSSIAN) == Selection("qwen3", "Ryan", "ru")  # when it is named
    assert replace(catalog, default_model="qwen3").resolve(text=RUSSIAN) == Selection("qwen3", "Ryan", "ru")


def test_chinese_and_japanese_texts_stay_with_the_default_model(catalog):
    assert catalog.resolve(text="你好，这是一个测试。") == Selection("kokoro", "zf_xiaobei", "zh")
    assert catalog.resolve(text="これは日本語のテストです。") == Selection("kokoro", "jf_alpha", "ja")


def test_a_korean_text_needs_a_model_that_speaks_korean(catalog):
    assert catalog.resolve(model="qwen3", text="안녕하세요, 테스트입니다.") == Selection("qwen3", "Sohee", "ko")
    with pytest.raises(SelectionError, match="Hangul"):
        catalog.resolve(text="안녕하세요, 테스트입니다.")


def test_a_latin_text_is_unchanged(catalog):
    assert catalog.resolve(text="Guten Tag") == catalog.resolve()
    assert catalog.resolve(model="qwen3", language="de", text="Guten Tag") == Selection("qwen3", "Ryan", "de")


def test_a_named_language_that_matches_the_text_is_accepted(catalog):
    assert catalog.resolve(model="qwen3", language="ru", text=RUSSIAN) == Selection("qwen3", "Ryan", "ru")
    assert catalog.resolve(model="qwen3", voice="Ryan", text=RUSSIAN) == Selection("qwen3", "Ryan", "ru")


def test_a_model_that_detects_the_language_itself_may_read_any_script(catalog):
    assert catalog.resolve(model="qwen3", language="auto", text=RUSSIAN) == Selection("qwen3", "Ryan", "auto")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"language": "en"}, "written in Cyrillic script but American English"),
        ({"voice": "af_heart"}, "has no language for it"),
        ({"language": "fr"}, "written in Cyrillic script but French"),
        ({"model": "kokoro"}, "has no language for it"),
    ],
)
def test_a_voice_or_language_that_cannot_read_the_text_is_refused(catalog, arguments, message):
    with pytest.raises(SelectionError, match=message) as error:
        catalog.resolve(text=RUSSIAN, **arguments)
    assert "list_models" in str(error.value)


# -- end to end ----------------------------------------------------------------------------------
def test_a_russian_text_is_refused_by_the_default_model_and_spoken_by_a_named_one(call_tool, fakes):
    refused = call_tool("start_speech", text=RUSSIAN)
    assert refused.is_error and "model 'kokoro' has no language for it" in refused.text
    assert not fakes.engine.calls and not fakes.qwen.calls
    result = call_tool("start_speech", text=RUSSIAN, model="qwen3")
    assert not result.is_error and "model qwen3" in result.text
    assert wait_until(lambda: fakes.qwen.calls)
    assert fakes.qwen.calls[0]["language"] == "Russian"
    assert not fakes.engine.calls  # the English Kokoro voice never saw the Cyrillic text


def test_the_english_default_voice_is_refused_for_a_russian_text(call_tool, fakes):
    result = call_tool("start_speech", text=RUSSIAN, voice="af_heart")
    assert result.is_error and "has no language for it" in result.text
    assert not fakes.engine.calls and not fakes.qwen.calls
    assert call_tool("speech_status").text.startswith("idle")  # nothing was started


def test_a_russian_text_with_a_wrong_language_is_refused_through_a_secondary_instance(make_app, fakes):
    make_app(pid=1111)
    secondary = make_app(pid=2222)
    result = call_tool_on(secondary, "start_speech", text=RUSSIAN, language="en")
    assert result.is_error and "written in Cyrillic script" in result.text


def test_a_model_whose_package_is_missing_is_refused_at_once_with_the_install_command(make_app, fakes, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "qwen_tts", None)  # makes `import qwen_tts` fail
    app = make_app()
    result = call_tool_on(app, "start_speech", text=RUSSIAN, model="qwen3")
    assert result.is_error
    assert "model 'qwen3' (Russian)" in result.text and "cannot run" in result.text
    assert "pip install -r requirements-qwen3.txt" in result.text
    assert call_tool_on(app, "speech_status").text.startswith("idle")  # nothing was started, nothing fails later
    assert not fakes.sd.streams


def test_the_default_model_is_checked_too(make_app, fakes, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "kokoro", None)
    app = make_app()
    result = call_tool_on(app, "start_speech", text="Hello")
    assert result.is_error and "pip install -r requirements-kokoro.txt" in result.text
