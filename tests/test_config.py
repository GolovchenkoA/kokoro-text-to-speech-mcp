"""Unit tests for Settings."""

from __future__ import annotations

from pathlib import Path

import pytest

from kokoro_mcp.config import DEFAULT_VAD_THRESHOLD, Settings


def test_defaults():
    settings = Settings.from_env({})
    assert settings == Settings()
    assert settings.default_voice == "af_heart"
    assert not settings.voice_control
    assert settings.vad_mode == "energy"
    assert settings.vad_threshold == DEFAULT_VAD_THRESHOLD


def test_values_are_read_from_the_environment():
    settings = Settings.from_env(
        {
            "KOKORO_DEFAULT_VOICE": "bm_george",
            "KOKORO_DEVICE": "cpu",
            "KOKORO_WAKEWORD": "1",
            "KOKORO_VOSK_MODEL": "/models/vosk",
            "KOKORO_MIC_DEVICE": "USB Mic",
            "KOKORO_VAD": "OFF",
            "KOKORO_VAD_THRESHOLD": "750",
            "KOKORO_SHARED_INSTANCE": "0",
            "KOKORO_IPC_DIR": "/tmp/kokoro-ipc",
        }
    )
    assert settings == Settings(
        default_voice="bm_george",
        device="cpu",
        voice_control=True,
        vosk_model="/models/vosk",
        mic_device="USB Mic",
        vad_mode="off",
        vad_threshold=750.0,
        shared_instance=False,
        ipc_dir=Path("/tmp/kokoro-ipc"),
    )


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_voice_control_truthy_values(value):
    assert Settings.from_env({"KOKORO_WAKEWORD": value}).voice_control


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "enable"])
def test_voice_control_other_values_are_off(value):
    assert not Settings.from_env({"KOKORO_WAKEWORD": value}).voice_control


def test_invalid_vad_settings_fall_back_to_defaults():
    settings = Settings.from_env({"KOKORO_VAD": "magic", "KOKORO_VAD_THRESHOLD": "loud"})
    assert settings.vad_mode == "energy"
    assert settings.vad_threshold == DEFAULT_VAD_THRESHOLD


def test_instances_are_shared_by_default_and_the_ipc_dir_is_in_the_home_directory():
    settings = Settings.from_env({})
    assert settings.shared_instance
    assert settings.resolved_ipc_dir == Path.home() / ".kokoro_mcp"


@pytest.mark.parametrize("value", ["0", "false", "no", "off"])
def test_shared_instance_can_be_turned_off(value):
    assert not Settings.from_env({"KOKORO_SHARED_INSTANCE": value}).shared_instance
