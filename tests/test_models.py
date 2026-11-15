"""End-to-end tests of model selection: the models file decides which engine speaks, with no code change."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import call_tool_on
from tests.fakes import CHUNK_FRAMES, EchoEngine, models_data, wait_until
from tts_mcp.devices import resolve_device
from tts_mcp.engines.text import split_text

REAL_MODELS = models_data()


def write_models(tmp_path, data, name="models.json"):
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def with_default(model_id):
    return {**REAL_MODELS, "default_model": model_id}


def status(app) -> str:
    return call_tool_on(app, "speech_status").text


# -- choosing a model per request ----------------------------------------------------------------
def test_the_default_model_speaks_when_nothing_else_is_asked(call_tool, fakes):
    text = call_tool("start_speech", text="Hello").text
    assert "model kokoro, voice af_heart" in text
    assert wait_until(lambda: fakes.engine.calls)
    assert not fakes.qwen.calls


def test_another_model_is_used_only_when_it_is_named(call_tool, fakes):
    refused = call_tool("start_speech", text="Hello", voice="Ryan")  # a voice of qwen3, but kokoro is the default
    assert refused.is_error and "unknown voice 'Ryan' in model 'kokoro'" in refused.text
    text = call_tool("start_speech", text="Hello", model="qwen3", voice="Ryan").text
    assert "model qwen3, voice Ryan" in text
    assert wait_until(lambda: fakes.qwen.calls)
    assert fakes.qwen.calls[0] == {"text": "Hello", "language": "Auto", "speaker": "Ryan"}
    assert not fakes.engine.calls


def test_a_language_the_default_model_lacks_is_not_supported_unless_a_model_is_named(call_tool, fakes):
    refused = call_tool("start_speech", text="Guten Tag", language="de")
    assert refused.is_error and "language 'de' is not supported in model 'kokoro'" in refused.text
    result = call_tool("start_speech", text="Guten Tag", model="qwen3", language="de")
    assert "model qwen3, voice Ryan" in result.text
    assert wait_until(lambda: fakes.qwen.calls)
    assert fakes.qwen.calls[0]["language"] == "German"


def test_a_model_can_be_named(call_tool, fakes):
    call_tool("start_speech", text="Hello", model="qwen3", language="en", voice="Aiden")
    assert wait_until(lambda: fakes.qwen.calls)
    assert fakes.qwen.calls[0] == {"text": "Hello", "language": "English", "speaker": "Aiden"}


def test_the_language_picks_the_default_voice_of_that_language(call_tool, fakes):
    call_tool("start_speech", text="Hello", language="en-gb")
    assert wait_until(lambda: fakes.engine.calls)
    assert (fakes.engine.calls[0]["lang"], fakes.engine.calls[0]["voice"]) == ("b", "bf_emma")


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"model": "nope"}, "unknown model"),
        ({"language": "pl"}, "language 'pl' is not supported"),
        ({"model": "kokoro", "voice": "Ryan"}, "unknown voice 'Ryan' in model 'kokoro'"),
    ],
)
def test_requests_no_model_can_serve_are_rejected(call_tool, arguments, message):
    result = call_tool("start_speech", text="Hello", **arguments)
    assert result.is_error and message in result.text


def test_selection_works_through_a_secondary_instance(make_app, fakes):
    make_app(pid=1111)
    secondary = make_app(pid=2222)
    result = call_tool_on(secondary, "start_speech", text="Hallo", model="qwen3", language="de")
    assert not result.is_error and "model qwen3" in result.text
    assert wait_until(lambda: fakes.qwen.calls)
    bad = call_tool_on(secondary, "start_speech", text="Hi", model="nope")
    assert bad.is_error and "unknown model" in bad.text


# -- engines are created once, lazily ------------------------------------------------------------
def test_a_model_is_loaded_only_when_first_used_and_then_kept(call_tool, fakes):
    assert not fakes.qwen.loads
    for _ in range(2):
        call_tool("start_speech", text="Hello", model="qwen3", voice="Ryan")
        assert wait_until(lambda: status_of(call_tool) == "finished")
    assert len(fakes.qwen.loads) == 1


def status_of(call_tool) -> str:
    return call_tool("speech_status").text


# -- switching the model by the file only --------------------------------------------------------
def test_another_default_model_is_a_change_to_the_file_only(make_app, fakes, tmp_path):
    app = make_app(models_file=write_models(tmp_path, with_default("qwen3")))
    result = call_tool_on(app, "start_speech", text="Hello")
    assert "model qwen3, voice Ryan" in result.text
    assert wait_until(lambda: fakes.qwen.calls)
    assert not fakes.engine.calls
    # what the new default model speaks is supported now, and what it lacks is not
    assert not call_tool_on(app, "start_speech", text="Hallo", language="de").is_error
    refused = call_tool_on(app, "start_speech", text="Hello", voice="af_heart")
    assert refused.is_error and "unknown voice 'af_heart' in model 'qwen3'" in refused.text


def test_the_sample_rate_comes_from_the_file(make_app, fakes, tmp_path):
    data = with_default("qwen3")
    data["models"]["qwen3"] = {**data["models"]["qwen3"], "sample_rate": 16000}
    app = make_app(models_file=write_models(tmp_path, data))
    call_tool_on(app, "start_speech", text="Hello")
    assert wait_until(lambda: fakes.sd.streams)
    assert fakes.sd.streams[-1].kwargs["samplerate"] == 16000
    assert wait_until(lambda: status(app) == "finished")
    # The fake model answers at 24 kHz: the engine resampled half a second to the file's rate.
    assert fakes.sd.streams[-1].frames == 8000


def test_a_model_with_a_new_engine_is_added_by_the_file_only(make_app, fakes, tmp_path):
    EchoEngine.created.clear()
    EchoEngine.calls.clear()
    data = {
        "default_model": "echo",
        "models": {
            "echo": {
                "name": "Echo",
                "engine": "tests.fakes:EchoEngine",
                "sample_rate": 22050,
                "languages": {"en": {"engine_code": "english", "voices": ["alice", "bob"]}},
            }
        },
    }
    app = make_app(models_file=write_models(tmp_path, data))

    started = call_tool_on(app, "start_speech", text="Hello there", voice="bob")
    assert "model echo, voice bob" in started.text
    assert wait_until(lambda: status(app) == "finished")
    assert EchoEngine.calls == [{"text": "Hello there", "voice": "bob", "language": "english"}]
    assert fakes.sd.streams[-1].kwargs["samplerate"] == 22050
    assert not fakes.engine.calls and not fakes.qwen.calls

    listed = call_tool_on(app, "list_models").text
    assert "echo" in listed and "alice" in listed and "kokoro" not in listed


def test_an_engine_that_cannot_be_loaded_is_refused_at_once(make_app, tmp_path):
    data = with_default("kokoro")
    data["models"]["kokoro"] = {**data["models"]["kokoro"], "engine": "no.such.module:Engine"}
    app = make_app(models_file=write_models(tmp_path, data))
    result = call_tool_on(app, "start_speech", text="Hello")
    assert result.is_error and "cannot load engine 'no.such.module:Engine'" in result.text
    assert status(app).startswith("idle")  # nothing was started


def test_an_invalid_models_file_stops_the_server_at_start(make_app, tmp_path):
    from tts_mcp.catalog import CatalogError

    with pytest.raises(CatalogError, match="'models' must be a non-empty object"):
        make_app(models_file=write_models(tmp_path, {"default_model": "x", "models": {}}))


# -- CPU fallback --------------------------------------------------------------------------------
def test_without_a_gpu_the_models_run_on_the_cpu(call_tool, fakes):
    call_tool("start_speech", text="Hello", model="qwen3", voice="Ryan")
    call_tool("start_speech", text="Hello")
    assert wait_until(lambda: fakes.qwen.loads and fakes.engine.calls)
    assert fakes.qwen.loads[0] == {"repo": REAL_MODELS["models"]["qwen3"]["options"]["repo"], "device_map": "cpu", "dtype": "float32"}
    assert fakes.engine.calls[0]["device"] == "cpu"


def test_with_a_gpu_it_is_used(call_tool, fakes):
    fakes.gpus["available"] = frozenset({"cpu", "cuda"})
    call_tool("start_speech", text="Hello", model="qwen3", voice="Ryan")
    call_tool("start_speech", text="Hello")
    assert wait_until(lambda: fakes.qwen.loads and fakes.engine.calls)
    assert fakes.qwen.loads[0]["device_map"] == "cuda:0" and fakes.qwen.loads[0]["dtype"] == "bfloat16"
    assert fakes.engine.calls[0]["device"] == "cuda"


def test_a_gpu_that_fails_to_load_a_model_falls_back_to_the_cpu(call_tool, fakes):
    fakes.gpus["available"] = frozenset({"cpu", "cuda"})
    fakes.qwen.fail_on_gpu = True
    call_tool("start_speech", text="Hello", model="qwen3", voice="Ryan")
    assert wait_until(lambda: len(fakes.qwen.loads) == 2)
    assert [load["device_map"] for load in fakes.qwen.loads] == ["cuda:0", "cpu"]
    assert wait_until(lambda: status_of(call_tool) == "finished")  # and it spoke


def test_a_device_that_is_asked_for_but_missing_falls_back_to_the_cpu(make_app, fakes):
    app = make_app(device="cuda")  # the fake machine has no GPU
    call_tool_on(app, "start_speech", text="Hello")
    assert wait_until(lambda: fakes.engine.calls)
    assert fakes.engine.calls[0]["device"] == "cpu"


@pytest.mark.parametrize(
    ("available", "requested", "expected"),
    [
        ({"cpu"}, None, "cpu"),
        ({"cpu"}, "auto", "cpu"),
        ({"cpu", "cuda"}, "auto", "cuda"),
        ({"cpu", "mps"}, "AUTO", "mps"),
        ({"cpu", "cuda", "mps"}, "auto", "cuda"),
        ({"cpu", "cuda"}, "cpu", "cpu"),
        ({"cpu", "cuda"}, "cuda", "cuda"),
        ({"cpu"}, "cuda", "cpu"),
        ({"cpu"}, "mps", "cpu"),
    ],
)
def test_device_choice(fakes, available, requested, expected):
    fakes.gpus["available"] = frozenset(available)
    assert resolve_device(requested) == expected


# -- text splitting for models that cannot stream ------------------------------------------------
def test_text_is_split_at_lines_and_sentences_and_packed_up_to_the_limit():
    text = "One. Two! Three?\nFour line"
    assert split_text(text, 1000) == ["One. Two! Three? Four line"]
    assert split_text(text, 10) == ["One. Two!", "Three?", "Four line"]


def test_a_sentence_longer_than_the_limit_is_cut_at_spaces():
    pieces = split_text("alpha beta gamma delta", 11)
    assert pieces == ["alpha beta", "gamma delta"]
    assert split_text("x" * 25, 10) == ["x" * 10, "x" * 10, "x" * 5]


def test_blank_text_gives_no_pieces():
    assert split_text(" \n\n ", 10) == []


def test_a_long_text_is_spoken_piece_by_piece_by_a_model_that_cannot_stream(call_tool, fakes):
    sentences = " ".join(f"Sentence number {i}." for i in range(60))  # ~1000 characters, limit is 300
    call_tool("start_speech", text=sentences, model="qwen3", voice="Ryan")
    assert wait_until(lambda: len(fakes.qwen.calls) >= 3)
    assert all(len(call["text"]) <= 300 for call in fakes.qwen.calls)
    assert wait_until(lambda: status_of(call_tool) == "finished")
    assert fakes.sd.streams[-1].frames == len(fakes.qwen.calls) * (CHUNK_FRAMES // 1)
