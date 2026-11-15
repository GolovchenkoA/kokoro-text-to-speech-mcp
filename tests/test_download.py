"""The pre-download command: reads the models file and fetches each model's repository."""

from __future__ import annotations

import json
import sys
import types

import pytest

from tests.fakes import models_data
from tts_mcp import download


@pytest.fixture
def hub(monkeypatch, tmp_path):
    """A fake huggingface_hub that records what would be downloaded."""
    requested: list[str] = []
    module = types.ModuleType("huggingface_hub")

    def snapshot_download(repo_id):
        requested.append(repo_id)
        if repo_id == "broken/repo":
            raise OSError("no network")
        return f"/cache/{repo_id}"

    module.snapshot_download = snapshot_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", module)
    pinned = tmp_path / "pinned-models.json"
    pinned.write_text(json.dumps(models_data()), encoding="utf-8")  # kokoro is the default, whatever the local file says
    monkeypatch.setenv("TTS_MODELS_FILE", str(pinned))
    return requested


def test_without_arguments_the_default_model_is_downloaded(hub, capsys):
    assert download.main([]) == 0
    assert hub == ["hexgrad/Kokoro-82M"]
    assert "kokoro: ready in" in capsys.readouterr().out


def test_models_can_be_named_or_all_can_be_asked_for(hub):
    assert download.main(["qwen3"]) == 0
    assert hub == ["Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"]
    hub.clear()
    assert download.main(["--all"]) == 0
    assert hub == ["hexgrad/Kokoro-82M", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"]


def test_an_unknown_model_is_rejected_before_anything_is_downloaded(hub, capsys):
    assert download.main(["kokoro", "nope"]) == 2
    assert hub == []
    assert "unknown model(s): nope" in capsys.readouterr().err


def test_a_failed_download_is_reported_and_the_others_still_run(hub, monkeypatch, tmp_path, capsys):
    models = {
        "default_model": "a",
        "models": {
            "a": {"engine": "x:Y", "sample_rate": 1, "options": {"repo": "broken/repo"}, "languages": {"en": {"voices": ["v"]}}},
            "b": {"engine": "x:Y", "sample_rate": 1, "options": {"repo": "good/repo"}, "languages": {"en": {"voices": ["v"]}}},
            "c": {"engine": "x:Y", "sample_rate": 1, "languages": {"en": {"voices": ["v"]}}},
        },
    }
    path = tmp_path / "models.json"
    path.write_text(json.dumps(models), encoding="utf-8")
    monkeypatch.setenv("TTS_MODELS_FILE", str(path))

    assert download.main(["--all"]) == 1
    assert hub == ["broken/repo", "good/repo"]
    captured = capsys.readouterr()
    assert "a: failed: no network" in captured.err
    assert "b: ready in /cache/good/repo" in captured.out
    assert "c: no 'repo'" in captured.out


def test_an_invalid_models_file_is_reported(hub, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TTS_MODELS_FILE", str(tmp_path / "missing.json"))
    assert download.main([]) == 2
    assert "cannot read the models file" in capsys.readouterr().err


def test_the_voice_control_model_is_downloaded_on_request(hub, monkeypatch, capsys):
    created = []
    vosk = types.ModuleType("vosk")
    vosk.Model = lambda **kwargs: created.append(kwargs)
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    monkeypatch.delenv("TTS_VOSK_MODEL", raising=False)

    assert download.main(["--voice-control"]) == 0
    assert created == [{"lang": "en-us"}]


def test_a_local_voice_control_model_needs_no_download(hub, monkeypatch, capsys):
    monkeypatch.setenv("TTS_VOSK_MODEL", "/models/vosk")
    assert download.main(["--voice-control"]) == 0
    assert "nothing to download" in capsys.readouterr().out


def test_a_model_whose_package_is_missing_is_reported_after_its_files_are_downloaded(hub, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "qwen_tts", None)  # makes `import qwen_tts` fail
    assert download.main(["qwen3"]) == 0  # the download itself worked
    captured = capsys.readouterr()
    assert "qwen3: ready in" in captured.out
    assert "files are downloaded, but the model cannot run yet" in captured.err
    assert "downloading the model files does not install it" in captured.err
    assert "pip install -r requirements-qwen3.txt" in captured.err


def test_nothing_is_reported_when_the_package_is_there(hub, monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "qwen_tts", types.ModuleType("qwen_tts"))
    monkeypatch.setitem(sys.modules, "torch", types.ModuleType("torch"))
    assert download.main(["qwen3"]) == 0
    assert "cannot run" not in capsys.readouterr().err
