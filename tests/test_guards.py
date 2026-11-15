"""The guard wrapper and the language guard: refuse what the model cannot read, skip what is too short."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

import server
from tests.conftest import call_tool_on
from tests.fakes import wait_until
from tts_mcp.catalog import SelectionError, default_models_file, load_catalog
from tts_mcp.config import Settings
from tts_mcp.detectors import Detection
from tts_mcp.guards import (
    MIN_CHARS,
    SAMPLE_CHARS,
    GuardedSpeech,
    LanguageGuard,
    SpeechRequest,
)

GERMAN = Detection("de", "German", 0.99)
POLISH = Detection("pl", "Polish", 0.99)
ENGLISH = Detection("en", "English", 0.99)
FRENCH = Detection("fr", "French", 0.99)
RUSSIAN = Detection("ru", "Russian", 0.99)


def long_text(length: int = 150) -> str:
    return ("This sentence is only here to make the text long enough. " * 20)[:length]


class FakeDetector:
    """Answers with a fixed detection and remembers what it was asked."""

    def __init__(self, detection: Detection | None) -> None:
        self.detection = detection
        self.seen: list[str] = []
        self.warmed_up = False

    def detect(self, text: str) -> Detection | None:
        self.seen.append(text)
        return self.detection

    def warm_up(self) -> None:
        self.warmed_up = True


@pytest.fixture(scope="module")
def catalog():
    """The shipped file: Kokoro is the default model."""
    return load_catalog(default_models_file())


@pytest.fixture(scope="module")
def qwen_catalog(catalog):
    """The same file with Qwen3 as the default model: a change to `default_model` only."""
    return replace(catalog, default_model="qwen3")


@pytest.fixture
def qwen_default_file(tmp_path):
    data = json.loads(default_models_file().read_text(encoding="utf-8"))
    data["default_model"] = "qwen3"
    path = tmp_path / "models-qwen-default.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def guard_for(catalog, detection):
    detector = FakeDetector(detection)
    return LanguageGuard(catalog, detector), detector


def request(text, voice=None, model=None, language=None):
    return SpeechRequest(text, voice, 1.0, model, language)


# -- what is checked -----------------------------------------------------------------------------
def test_a_text_below_120_characters_is_not_checked_and_counts_as_supported(catalog):
    guard, detector = guard_for(catalog, POLISH)  # would be refused if it were looked at
    for length in (1, 50, MIN_CHARS - 1):
        original = request(long_text(length))
        assert guard.check(original) is original
    assert detector.seen == []


def test_the_length_is_counted_without_surrounding_blanks(catalog):
    guard, detector = guard_for(catalog, POLISH)
    guard.check(request("   " + long_text(MIN_CHARS - 1) + "   \n"))
    assert detector.seen == []


def test_a_text_of_120_characters_is_checked(catalog):
    guard, detector = guard_for(catalog, ENGLISH)
    guard.check(request(long_text(MIN_CHARS)))
    assert len(detector.seen) == 1


def test_only_the_first_200_characters_are_looked_at(catalog):
    guard, detector = guard_for(catalog, ENGLISH)
    text = "A" * SAMPLE_CHARS + "B" * 5000
    guard.check(request(text))
    assert detector.seen == ["A" * SAMPLE_CHARS]


def test_an_answer_that_is_unsure_or_missing_counts_as_supported(catalog):
    for detection in (None, Detection("pl", "Polish", 0.5)):
        guard, _ = guard_for(catalog, detection)
        original = request(long_text())
        assert guard.check(original) is original


# -- the default model decides what is supported -------------------------------------------------
def test_a_language_the_default_model_lacks_is_refused_with_the_languages_it_speaks(catalog):
    guard, _ = guard_for(catalog, POLISH)
    with pytest.raises(SelectionError, match=r"detected as Polish \(pl\) and it is not supported by the model") as error:
        guard.check(request(long_text()))
    supported = str(error.value).split("Supported languages:")[1]
    assert "American English" in supported and "French" in supported  # what the default model speaks
    assert "German" not in supported  # qwen3 speaks it, but it is not the default model: not counted


def test_a_language_only_another_model_speaks_is_refused_unless_that_model_is_named(catalog):
    guard, _ = guard_for(catalog, GERMAN)  # qwen3 speaks German, kokoro (the default) does not
    with pytest.raises(SelectionError, match=r"detected as German \(de\) and it is not supported by the model"):
        guard.check(request(long_text()))
    assert guard.check(request(long_text(), model="qwen3")).language == "de"


def test_when_the_default_model_is_changed_its_languages_are_the_supported_ones(qwen_catalog):
    guard, _ = guard_for(qwen_catalog, GERMAN)
    assert guard.check(request(long_text())).language == "de"
    guard, _ = guard_for(qwen_catalog, Detection("hi", "Hindi", 0.99))  # kokoro speaks Hindi, qwen3 does not
    with pytest.raises(SelectionError, match="Hindi"):
        guard.check(request(long_text()))


def test_the_detected_language_is_passed_on_when_the_caller_named_none(catalog):
    guard, _ = guard_for(catalog, FRENCH)
    assert guard.check(request(long_text())).language == "fr"


def test_a_language_that_is_named_is_checked_against_the_text(qwen_catalog):
    guard, _ = guard_for(qwen_catalog, GERMAN)
    named = request(long_text(), language="de")
    assert guard.check(named) is named
    with pytest.raises(SelectionError, match=r"The text is in German \(de\) but English"):
        guard.check(request(long_text(), language="en"))


def test_a_voice_that_cannot_read_the_text_is_refused(catalog, qwen_catalog):
    guard, _ = guard_for(catalog, FRENCH)
    with pytest.raises(SelectionError, match=r"voice 'af_heart', model 'kokoro'.*Pass language 'fr'"):
        guard.check(request(long_text(), voice="af_heart"))  # kokoro speaks French, but not with this voice
    guard, _ = guard_for(qwen_catalog, GERMAN)
    ryan = request(long_text(), voice="Ryan")  # Qwen3 voices read any language
    assert guard.check(ryan) is ryan


def test_a_named_model_that_lacks_the_language_is_refused(catalog):
    guard, _ = guard_for(catalog, GERMAN)
    with pytest.raises(SelectionError, match="not supported by the model"):
        guard.check(request(long_text(), model="kokoro"))


def test_an_unknown_voice_is_reported_by_the_catalogue(qwen_catalog):
    guard, _ = guard_for(qwen_catalog, GERMAN)
    with pytest.raises(SelectionError, match="unknown voice 'xx_nobody'"):
        guard.check(request(long_text(), voice="xx_nobody"))


def test_an_unknown_model_is_left_to_the_catalogue(catalog):
    guard, _ = guard_for(catalog, GERMAN)
    original = request(long_text(), model="nope")
    assert guard.check(original) is original


# -- the wrapper ---------------------------------------------------------------------------------
class RecordingSpeech:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def start(self, text, voice, speed, model=None, language=None):
        self.calls.append(("start", text, voice, speed, model, language))
        return {"characters": len(text), "model": "m", "voice": "v", "language": "l"}

    def pause(self):
        self.calls.append(("pause",))
        return True

    def resume(self):
        self.calls.append(("resume",))
        return True

    def stop(self):
        self.calls.append(("stop",))
        return True

    def describe(self):
        return "idle"

    def state_label(self):
        return "idle"

    def shutdown(self):
        self.calls.append(("shutdown",))


class Upper:
    def check(self, req):
        return SpeechRequest(req.text.upper(), req.voice, req.speed, req.model, req.language)


class Refuse:
    def check(self, req):
        raise SelectionError("no")


def test_guards_run_in_order_and_each_sees_the_previous_result():
    inner = RecordingSpeech()
    GuardedSpeech(inner, [Upper(), Upper()]).start("abc", "v", 1.5, "m", "l")
    assert inner.calls == [("start", "ABC", "v", 1.5, "m", "l")]


def test_a_refusing_guard_stops_the_chain_and_the_backend_is_not_called():
    inner = RecordingSpeech()
    with pytest.raises(SelectionError):
        GuardedSpeech(inner, [Refuse(), Upper()]).start("abc", "v", 1.0)
    assert inner.calls == []


def test_every_other_call_passes_through_unchecked():
    inner = RecordingSpeech()
    speech = GuardedSpeech(inner, [Refuse()])  # would refuse any start
    assert speech.pause() and speech.resume() and speech.stop()
    assert (speech.describe(), speech.state_label()) == ("idle", "idle")
    speech.shutdown()
    assert [call[0] for call in inner.calls] == ["pause", "resume", "stop", "shutdown"]


# -- through the MCP tool ------------------------------------------------------------------------
def test_an_unsupported_language_gets_an_error_response_and_nothing_is_spoken(make_app, fakes):
    app = make_app(detector=FakeDetector(POLISH))
    result = call_tool_on(app, "start_speech", text=long_text())
    assert result.is_error and "detected as Polish (pl) and it is not supported by the model" in result.text
    assert call_tool_on(app, "speech_status").text.startswith("idle")
    assert not fakes.engine.calls and not fakes.qwen.calls and not fakes.sd.streams


def test_a_russian_text_is_reported_as_unsupported_while_qwen3_is_not_the_default(make_app, fakes):
    app = make_app(detector=FakeDetector(RUSSIAN))
    result = call_tool_on(app, "start_speech", text=long_text())
    assert result.is_error
    assert "detected as Russian (ru) and it is not supported by the model" in result.text
    assert not fakes.qwen.calls and not fakes.sd.streams


def test_a_language_of_the_default_model_is_spoken_by_it(make_app, fakes, qwen_default_file):
    app = make_app(detector=FakeDetector(GERMAN), models_file=qwen_default_file)  # qwen3 is the default here
    result = call_tool_on(app, "start_speech", text=long_text())
    assert not result.is_error and "model qwen3" in result.text
    assert wait_until(lambda: fakes.qwen.calls)
    assert fakes.qwen.calls[0]["language"] == "German"


def test_english_stays_with_the_default_model(make_app, fakes):
    app = make_app(detector=FakeDetector(ENGLISH))
    assert "model kokoro, voice af_heart" in call_tool_on(app, "start_speech", text=long_text()).text


def test_short_text_is_spoken_without_asking_the_detector(make_app, fakes):
    detector = FakeDetector(POLISH)
    app = make_app(detector=detector)
    assert not call_tool_on(app, "start_speech", text="Dzień dobry").is_error
    assert detector.seen == []


def test_the_other_tools_are_not_guarded(make_app, fakes):
    app = make_app(detector=FakeDetector(POLISH))
    assert call_tool_on(app, "pause_speech").text.startswith("Nothing to pause")
    assert call_tool_on(app, "speech_status").text.startswith("idle")
    assert not call_tool_on(app, "list_models").is_error


# -- switching the check off ---------------------------------------------------------------------
def test_the_check_can_be_turned_off(make_app, fakes):
    detector = FakeDetector(POLISH)
    app = make_app(detector=detector, language_check=False)
    assert app.detector is None
    assert not call_tool_on(app, "start_speech", text=long_text()).is_error
    assert detector.seen == []


def test_without_the_detector_package_the_server_runs_unchecked(make_app, monkeypatch):
    monkeypatch.setattr(server, "lingua_is_installed", lambda: False)
    app = make_app(language_check=True)
    assert app.detector is None


@pytest.mark.parametrize(("value", "expected"), [("0", False), ("off", False), ("1", True), ("", True)])
def test_the_check_setting_comes_from_the_environment(value, expected):
    assert Settings.from_env({"TTS_LANGUAGE_CHECK": value}).language_check is expected
    assert Settings().language_check is True


# -- the real detector ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def lingua_detector():
    pytest.importorskip("lingua")
    from tts_mcp.detectors import LinguaDetector

    return LinguaDetector()


SAMPLES = {
    "en": "Hello everyone, this is a longer piece of English text that we are going to read aloud with the local model.",
    "de": "Guten Tag zusammen, dies ist ein längerer deutscher Text, den wir mit dem lokalen Sprachmodell vorlesen lassen.",
    "pl": "Dzień dobry wszystkim, to jest dłuższy polski tekst, który odczytamy na głos za pomocą lokalnego modelu mowy.",
    "ru": "Привет всем, это более длинный русский текст, который мы прочитаем вслух с помощью локальной модели речи.",
}


@pytest.mark.parametrize("code", list(SAMPLES))
def test_lingua_recognizes_the_language(lingua_detector, code):
    detection = lingua_detector.detect(SAMPLES[code][:SAMPLE_CHARS])
    assert detection.code == code and detection.confidence > 0.8


def test_lingua_names_the_language_in_english(lingua_detector):
    assert lingua_detector.detect(SAMPLES["pl"]).name == "Polish"


def test_the_guard_with_lingua_follows_the_default_model(catalog, qwen_catalog, lingua_detector):
    def long(code):  # the guard skips texts below 120 characters
        return SAMPLES[code] + " " + SAMPLES[code]

    kokoro_default = LanguageGuard(catalog, lingua_detector)
    assert kokoro_default.check(request(long("en"))).language == "en"
    for code in ("pl", "de", "ru"):  # none of these is spoken by Kokoro
        with pytest.raises(SelectionError, match="not supported by the model"):
            kokoro_default.check(request(long(code)))

    qwen_default = LanguageGuard(qwen_catalog, lingua_detector)
    assert qwen_default.check(request(long("de"))).language == "de"
    assert qwen_default.check(request(long("ru"))).language == "ru"
    with pytest.raises(SelectionError, match="Polish"):
        qwen_default.check(request(long("pl")))  # qwen3 has no Polish either
    short = request(SAMPLES["pl"][:100])
    assert qwen_default.check(short) is short  # under 120 characters: not checked
