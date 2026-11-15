"""Constants and environment-driven settings."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

SAMPLE_RATE = 24_000  # output sample rate of the speech model
MIC_RATE = 16_000  # microphone sample rate used for voice control
MAX_CHARS = 20_000  # longest text accepted by one start_speech call
DEFAULT_VOICE = "af_heart"
DEFAULT_VAD_THRESHOLD = 500.0  # RMS on the int16 scale; speech is typically 1000+, a quiet room < 300

_FALSE_VALUES = ("0", "false", "no", "off")


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Build it with `Settings.from_env()` or pass the fields directly."""

    default_voice: str = DEFAULT_VOICE
    device: str | None = None  # "cpu", "cuda", "mps" or None for auto
    is_voice_control_enabled: bool = True  # microphone commands; TTS_VOICE_CONTROL_ENABLED=0 turns them off
    vosk_model: str | None = None  # local Vosk model folder; None downloads the small English model
    mic_device: str | None = None
    vad_mode: str = "energy"  # "energy" or "off"
    vad_threshold: float = DEFAULT_VAD_THRESHOLD
    shared_instance: bool = True  # False: every server copy works on its own (no primary/secondary)
    ipc_dir: Path | None = None  # where the shared key lives; None = ~/.tts_mcp

    @property
    def resolved_ipc_dir(self) -> Path:
        return self.ipc_dir or Path.home() / ".tts_mcp"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environ is None else environ

        vad_mode = env.get("TTS_VAD", "energy").strip().lower()
        if vad_mode not in ("energy", "off"):
            log.warning("Unknown TTS_VAD=%r, using 'energy'", vad_mode)
            vad_mode = "energy"

        vad_threshold = DEFAULT_VAD_THRESHOLD
        raw_threshold = env.get("TTS_VAD_THRESHOLD")
        if raw_threshold:
            try:
                vad_threshold = float(raw_threshold)
            except ValueError:
                log.warning("Invalid TTS_VAD_THRESHOLD=%r, using %s", raw_threshold, DEFAULT_VAD_THRESHOLD)

        return cls(
            default_voice=env.get("TTS_DEFAULT_VOICE", DEFAULT_VOICE),
            device=env.get("TTS_DEVICE") or None,
            is_voice_control_enabled=env.get("TTS_VOICE_CONTROL_ENABLED", "1").lower() not in _FALSE_VALUES,
            vosk_model=env.get("TTS_VOSK_MODEL") or None,
            mic_device=env.get("TTS_MIC_DEVICE") or None,
            vad_mode=vad_mode,
            vad_threshold=vad_threshold,
            shared_instance=env.get("TTS_SHARED_INSTANCE", "1").lower() not in _FALSE_VALUES,
            ipc_dir=Path(env["TTS_IPC_DIR"]) if env.get("TTS_IPC_DIR") else None,
        )
