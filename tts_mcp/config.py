"""Constants and environment-driven settings.

Which models exist and which voices they have is not here: see ``models.json`` and ``tts_mcp.catalog``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tts_mcp.catalog import default_models_file

log = logging.getLogger(__name__)

MIC_RATE = 16_000  # microphone sample rate used for voice control
MAX_CHARS = 20_000  # longest text accepted by one start_speech call
DEFAULT_VAD_THRESHOLD = 500.0  # RMS on the int16 scale; speech is typically 1000+, a quiet room < 300

_FALSE_VALUES = ("0", "false", "no", "off")


@dataclass(frozen=True)
class Settings:
    """Runtime configuration. Build it with `Settings.from_env()` or pass the fields directly."""

    models_file: Path | None = None  # the models catalogue; None = models.json next to the package
    device: str | None = None  # "cpu", "cuda", "mps" or None: use each model's own setting (default auto)
    is_voice_control_enabled: bool = True  # microphone commands; TTS_VOICE_CONTROL_ENABLED=0 turns them off
    vosk_model: str | None = None  # local Vosk model folder; None downloads the small English model
    mic_device: str | None = None
    vad_mode: str = "energy"  # "energy" or "off"
    vad_threshold: float = DEFAULT_VAD_THRESHOLD
    language_check: bool = True  # refuse texts in a language no model speaks; TTS_LANGUAGE_CHECK=0 turns it off
    shared_instance: bool = True  # False: every server copy works on its own (no primary/secondary)
    ipc_dir: Path | None = None  # where the shared key lives; None = ~/.tts_mcp

    @property
    def resolved_ipc_dir(self) -> Path:
        return self.ipc_dir or Path.home() / ".tts_mcp"

    @property
    def resolved_models_file(self) -> Path:
        return self.models_file or default_models_file()

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
            models_file=Path(env["TTS_MODELS_FILE"]) if env.get("TTS_MODELS_FILE") else None,
            device=env.get("TTS_DEVICE") or None,
            is_voice_control_enabled=env.get("TTS_VOICE_CONTROL_ENABLED", "1").lower() not in _FALSE_VALUES,
            vosk_model=env.get("TTS_VOSK_MODEL") or None,
            mic_device=env.get("TTS_MIC_DEVICE") or None,
            vad_mode=vad_mode,
            vad_threshold=vad_threshold,
            language_check=env.get("TTS_LANGUAGE_CHECK", "1").lower() not in _FALSE_VALUES,
            shared_instance=env.get("TTS_SHARED_INSTANCE", "1").lower() not in _FALSE_VALUES,
            ipc_dir=Path(env["TTS_IPC_DIR"]) if env.get("TTS_IPC_DIR") else None,
        )
