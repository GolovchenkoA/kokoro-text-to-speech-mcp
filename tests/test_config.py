"""Unit tests for Settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from tts_mcp.config import DEFAULT_VAD_THRESHOLD, Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings == Settings()
    assert settings.models_file is None
    assert settings.resolved_models_file.name == "models.json"
    assert settings.is_voice_control_enabled  # on by default
    assert settings.vad_mode == "energy"
    assert settings.vad_threshold == DEFAULT_VAD_THRESHOLD


def test_values_are_read_from_the_environment():
    settings = Settings.from_env(
        {
            "TTS_MODELS_FILE": "/etc/tts/models.json",
            "TTS_DEVICE": "cpu",
            "TTS_VOICE_CONTROL_ENABLED": "0",
            "TTS_VOSK_MODEL": "/models/vosk",
            "TTS_MIC_DEVICE": "USB Mic",
            "TTS_VAD": "OFF",
            "TTS_VAD_THRESHOLD": "750",
            "TTS_SHARED_INSTANCE": "0",
            "TTS_IPC_DIR": "/tmp/tts-ipc",
        }
    )
    assert settings == Settings(
        models_file=Path("/etc/tts/models.json"),
        device="cpu",
        is_voice_control_enabled=False,
        vosk_model="/models/vosk",
        mic_device="USB Mic",
        vad_mode="off",
        vad_threshold=750.0,
        shared_instance=False,
        ipc_dir=Path("/tmp/tts-ipc"),
    )


def test_voice_control_is_on_by_default():
    assert Settings().is_voice_control_enabled
    assert Settings.from_env({}).is_voice_control_enabled  # TTS_VOICE_CONTROL_ENABLED not set


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "", "enable"])
def test_voice_control_stays_on_unless_switched_off(value):
    assert Settings.from_env({"TTS_VOICE_CONTROL_ENABLED": value}).is_voice_control_enabled


@pytest.mark.parametrize("value", ["0", "false", "FALSE", "no", "off", "OFF"])
def test_voice_control_can_be_switched_off(value):
    assert not Settings.from_env({"TTS_VOICE_CONTROL_ENABLED": value}).is_voice_control_enabled


def test_invalid_vad_settings_fall_back_to_defaults():
    settings = Settings.from_env({"TTS_VAD": "magic", "TTS_VAD_THRESHOLD": "loud"})
    assert settings.vad_mode == "energy"
    assert settings.vad_threshold == DEFAULT_VAD_THRESHOLD


def test_instances_are_shared_by_default_and_the_ipc_dir_is_in_the_home_directory():
    settings = Settings.from_env({})
    assert settings.shared_instance
    assert settings.resolved_ipc_dir == Path.home() / ".tts_mcp"


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_shared_instance_can_be_turned_off(value):
    assert not Settings.from_env({"TTS_SHARED_INSTANCE": value}).shared_instance
