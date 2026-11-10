"""Kokoro TTS MCP server.

Exposes tools to Claude Desktop over stdio:
  - speak(text, voice, speed, filename, play, save) -> generated .wav and/or live playback
  - play_file(path, wait) -> play an existing .wav on the local speakers
  - list_voices() -> available voice IDs grouped by language
"""

from __future__ import annotations

import logging
import os
import queue
import re
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from mcp.server.mcpserver import MCPServer

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

mcp = MCPServer("kokoro-tts")

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


class _StreamPlayer:
    """Plays audio chunks on the default output device from a background thread,
    so synthesis of the next chunk overlaps with playback of the previous one."""

    def __init__(self) -> None:
        import sounddevice as sd  # lazy: only needed when play=True

        # Open in the caller's thread so a missing/busy audio device fails fast.
        self._stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        self._stream.start()
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="kokoro-playback", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            while (chunk := self._queue.get()) is not None:
                self._stream.write(chunk.reshape(-1, 1))
        except BaseException as exc:  # surfaced in close()
            self._error = exc
        finally:
            self._stream.stop()
            self._stream.close()

    def feed(self, chunk: np.ndarray) -> None:
        self._queue.put(np.ascontiguousarray(chunk, dtype=np.float32))

    def close(self) -> None:
        """Wait for queued audio to finish playing, then release the device."""
        self._queue.put(None)
        self._thread.join()
        if self._error is not None:
            raise RuntimeError(f"audio playback failed: {self._error}") from self._error


def _safe_filename(name: str | None) -> str:
    if not name:
        return f"kokoro_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "kokoro"
    return f"{stem}.wav"


@mcp.tool()
def speak(
    text: str,
    voice: str = DEFAULT_VOICE,
    speed: float = 1.0,
    filename: str | None = None,
    play: bool = False,
    save: bool = True,
) -> str:
    """Convert text to speech with Kokoro, optionally playing it live and/or saving a WAV file.

    Args:
        text: The text to synthesize. Long text is split into chunks automatically.
        voice: Kokoro voice ID, e.g. "af_heart", "bm_george", "ff_siwis". The first
            letter selects the language (see list_voices).
        speed: Speaking rate, 0.5–2.0 (1.0 = normal).
        filename: Optional output file name (saved in the output directory).
        play: If true, stream each chunk to the speakers as soon as it is generated,
            so long texts start playing almost immediately. Returns after playback ends.
        save: If true (default), also write the audio to a WAV file. Set to false with
            play=true for playback only.

    Returns:
        A short message with the absolute path of the generated file (if saved) and the duration.
    """
    text = text.strip()
    if not text:
        raise ValueError("text is empty")
    if len(text) > MAX_CHARS:
        raise ValueError(f"text is too long ({len(text)} chars, max {MAX_CHARS})")
    if not play and not save:
        raise ValueError("nothing to do: set play=true and/or save=true")

    lang_code = voice[:1].lower()
    if lang_code not in LANGUAGES:
        raise ValueError(f"unknown voice '{voice}'. Call list_voices for valid IDs.")
    speed = min(max(speed, 0.5), 2.0)

    pipeline = _get_pipeline(lang_code)
    player = _StreamPlayer() if play else None
    chunks: list[np.ndarray] = []
    try:
        for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
            if audio is None:
                continue
            chunk = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
            chunks.append(chunk)
            if player:
                player.feed(chunk)
    finally:
        if player:
            player.close()  # blocks until playback has finished

    if not chunks:
        raise RuntimeError("Kokoro produced no audio for this text")

    waveform = np.concatenate(chunks)
    duration = len(waveform) / SAMPLE_RATE
    played = " Played on speakers." if play else ""

    if not save:
        return f"Generated {duration:.1f}s of audio (not saved).{played}"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / _safe_filename(filename)
    sf.write(out_path, waveform, SAMPLE_RATE)
    log.info("Wrote %s (%.1fs)", out_path, duration)
    return f"Saved {duration:.1f}s of audio to {out_path.resolve()}.{played}"


@mcp.tool()
def play_file(path: str, wait: bool = True) -> str:
    """Play an existing WAV file on the local speakers.

    Args:
        path: Path to a .wav file. A bare file name is looked up in the output directory.
        wait: If true (default), return after playback finishes; if false, return immediately
            and let it play in the background (a later play_file call replaces it).
    """
    file = Path(path).expanduser()
    if not file.is_absolute() and not file.exists():
        file = OUTPUT_DIR / file
    file = file.resolve()
    if file.suffix.lower() != ".wav":
        raise ValueError("only .wav files are supported")
    if not file.is_file():
        raise FileNotFoundError(f"no such file: {file}")

    if sys.platform == "win32":
        import winsound

        flags = winsound.SND_FILENAME | (0 if wait else winsound.SND_ASYNC)
        winsound.PlaySound(str(file), flags)
    else:
        import sounddevice as sd

        data, rate = sf.read(file, dtype="float32")
        sd.play(data, rate)
        if wait:
            sd.wait()
    return f"Played {file}" if wait else f"Started playing {file}"


@mcp.tool()
def list_voices() -> dict[str, list[str]]:
    """List Kokoro voice IDs grouped by language. Prefix: af/am = US female/male, bf/bm = UK, etc."""
    return {LANGUAGES[code]: voices for code, voices in VOICES.items()}


if __name__ == "__main__":
    mcp.run()  # stdio transport
