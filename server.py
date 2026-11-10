"""Kokoro TTS MCP server.

Exposes two tools to Claude Desktop over stdio:
  - speak(text, voice, speed, filename) -> path to a generated .wav
  - list_voices() -> available voice IDs grouped by language
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from mcp.server.fastmcp import FastMCP

# stdout is the MCP transport — all logging must go to stderr.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kokoro-mcp")

SAMPLE_RATE = 24_000
OUTPUT_DIR = Path(os.environ.get("KOKORO_OUTPUT_DIR", Path.home() / "kokoro_output")).expanduser()
DEFAULT_VOICE = os.environ.get("KOKORO_DEFAULT_VOICE", "af_heart")
DEVICE = os.environ.get("KOKORO_DEVICE")  # "cpu", "cuda", "mps" or unset for auto
MAX_CHARS = 20_000

# First letter of a voice ID == Kokoro lang_code.
LANGUAGES = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}

VOICES = {
    "a": ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael", "am_fenrir", "am_puck"],
    "b": ["bf_emma", "bf_isabella", "bm_george", "bm_fable"],
    "e": ["ef_dora", "em_alex"],
    "f": ["ff_siwis"],
    "h": ["hf_alpha", "hf_beta", "hm_omega"],
    "i": ["if_sara", "im_nicola"],
    "j": ["jf_alpha", "jf_gongitsune", "jm_kumo"],
    "p": ["pf_dora", "pm_alex"],
    "z": ["zf_xiaobei", "zf_xiaoni", "zm_yunjian"],
}

mcp = FastMCP("kokoro-tts")

_pipelines: dict[str, object] = {}
_lock = threading.Lock()


def _get_pipeline(lang_code: str):
    """Lazily create one KPipeline per language (model weights are shared/cached by Kokoro)."""
    with _lock:
        if lang_code not in _pipelines:
            from kokoro import KPipeline  # heavy import: defer until first use

            log.info("Loading Kokoro pipeline for lang_code=%s", lang_code)
            kwargs = {"lang_code": lang_code, "repo_id": "hexgrad/Kokoro-82M"}
            if DEVICE:
                kwargs["device"] = DEVICE
            _pipelines[lang_code] = KPipeline(**kwargs)
        return _pipelines[lang_code]


def _safe_filename(name: str | None) -> str:
    if not name:
        return f"kokoro_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "kokoro"
    return f"{stem}.wav"


@mcp.tool()
def speak(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0, filename: str | None = None) -> str:
    """Convert text to speech with Kokoro and save it as a WAV file.

    Args:
        text: The text to synthesize. Long text is split into chunks automatically.
        voice: Kokoro voice ID, e.g. "af_heart", "bm_george", "ff_siwis". The first
            letter selects the language (see list_voices).
        speed: Speaking rate, 0.5–2.0 (1.0 = normal).
        filename: Optional output file name (saved in the output directory).

    Returns:
        A short message with the absolute path of the generated file and its duration.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is empty")
    if len(text) > MAX_CHARS:
        raise ValueError(f"text is too long ({len(text)} chars, max {MAX_CHARS})")

    lang_code = voice[:1].lower()
    if lang_code not in LANGUAGES:
        raise ValueError(f"unknown voice '{voice}'. Call list_voices for valid IDs.")
    speed = min(max(speed, 0.5), 2.0)

    pipeline = _get_pipeline(lang_code)
    chunks = []
    for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
        if audio is not None:
            chunks.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))

    if not chunks:
        raise RuntimeError("Kokoro produced no audio for this text")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / _safe_filename(filename)
    waveform = np.concatenate(chunks)
    sf.write(out_path, waveform, SAMPLE_RATE)

    duration = len(waveform) / SAMPLE_RATE
    log.info("Wrote %s (%.1fs)", out_path, duration)
    return f"Saved {duration:.1f}s of audio to {out_path.resolve()}"


@mcp.tool()
def list_voices() -> dict[str, list[str]]:
    """List Kokoro voice IDs grouped by language. Prefix: af/am = US female/male, bf/bm = UK, etc."""
    return {LANGUAGES[code]: voices for code, voices in VOICES.items()}


if __name__ == "__main__":
    mcp.run()  # stdio transport
