"""Kokoro TTS MCP server.

Exposes tools to Claude Desktop over stdio:
  - start_speech(text, voice, speed) -> speak text in the background (in memory, no files)
  - pause_speech() / resume_speech() / stop_speech() / speech_status() -> control it
  - list_voices() -> available voice IDs grouped by language
(speak and play_file are disabled; their code is kept commented out below.)
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


SLICE_FRAMES = SAMPLE_RATE // 20  # 50 ms: granularity of pause/stop while audio is playing


class _SpeechSession:
    """One in-memory speech: a generator thread synthesizes chunks into a bounded queue and a
    playback thread streams them to the speakers in 50 ms slices. Nothing is written to disk.

    State: playing <-> paused, then finished | stopped | error
    """

    def __init__(self, text: str, voice: str, speed: float) -> None:
        import sounddevice as sd  # lazy: only needed when speech is started

        self.state = "playing"
        self.error: str | None = None
        self._text, self._voice, self._speed = text, voice, speed
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=3)  # bounds look-ahead while paused
        self._stop = threading.Event()
        self._running = threading.Event()  # set = playing, cleared = paused
        self._running.set()
        # Open in the caller's thread so a missing/busy audio device fails fast.
        self._stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32")
        self._generator = threading.Thread(target=self._generate, name="kokoro-generate", daemon=True)
        self._player = threading.Thread(target=self._play, name="kokoro-play", daemon=True)
        self._generator.start()
        self._player.start()

    # -- controls (called from tool handlers) ---------------------------------------------
    def pause(self) -> bool:
        if self.state != "playing":
            return False
        self._running.clear()
        self.state = "paused"
        return True

    def resume(self) -> bool:
        if self.state != "paused":
            return False
        self.state = "playing"
        self._running.set()
        return True

    def stop(self) -> bool:
        if self.state not in ("playing", "paused"):
            return False
        self.state = "stopped"
        self._stop.set()
        self._running.set()  # wake the player if it is paused
        return True

    def join(self, timeout: float) -> None:
        self._player.join(timeout)

    # -- worker threads -------------------------------------------------------------------
    def _put(self, item: np.ndarray | None) -> bool:
        """Queue an item, giving up if the session is stopped. Returns False when stopped."""
        while not self._stop.is_set():
            try:
                self._queue.put(item, timeout=0.1)
                return True
            except queue.Full:
                continue
        return False

    def _fail(self, exc: BaseException) -> None:
        log.exception("speech session failed")
        self.error = str(exc)
        if self.state in ("playing", "paused"):
            self.state = "error"
        self._stop.set()
        self._running.set()

    def _generate(self) -> None:
        try:
            pipeline = _get_pipeline(self._voice[:1].lower())  # may load the model: runs off the tool thread
            produced = False
            for _graphemes, _phonemes, audio in pipeline(
                self._text, voice=self._voice, speed=self._speed, split_pattern=r"\n+"
            ):
                if self._stop.is_set():
                    return
                if audio is None:
                    continue
                chunk = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
                produced = True
                if not self._put(np.ascontiguousarray(chunk, dtype=np.float32)):
                    return
            if not produced:
                raise RuntimeError("Kokoro produced no audio for this text")
            self._put(None)  # end-of-speech marker
        except BaseException as exc:
            self._fail(exc)

    def _play(self) -> None:
        try:
            self._stream.start()
            while not self._stop.is_set():
                try:
                    chunk = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if chunk is None:
                    break
                for i in range(0, len(chunk), SLICE_FRAMES):
                    self._running.wait()  # blocks while paused
                    if self._stop.is_set():
                        break
                    self._stream.write(chunk[i : i + SLICE_FRAMES].reshape(-1, 1))
            if self._stop.is_set():
                self._stream.abort()  # drop buffered audio immediately
            else:
                self._stream.stop()  # let buffered audio finish
                if self.state in ("playing", "paused"):
                    self.state = "finished"
        except BaseException as exc:
            self._fail(exc)
        finally:
            try:
                self._stream.close()
            except Exception:
                pass


_session: _SpeechSession | None = None
_session_lock = threading.Lock()


def _safe_filename(name: str | None) -> str:
    if not name:
        return f"kokoro_{time.strftime('%Y%m%d_%H%M%S')}.wav"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(name).stem).strip("._") or "kokoro"
    return f"{stem}.wav"


# @mcp.tool()
# def speak(
#     text: str,
#     voice: str = DEFAULT_VOICE,
#     speed: float = 1.0,
#     filename: str | None = None,
#     play: bool = False,
#     save: bool = True,
# ) -> str:
#     """Convert text to speech with Kokoro, optionally playing it live and/or saving a WAV file.
#
#     Args:
#         text: The text to synthesize. Long text is split into chunks automatically.
#         voice: Kokoro voice ID, e.g. "af_heart", "bm_george", "ff_siwis". The first
#             letter selects the language (see list_voices).
#         speed: Speaking rate, 0.5–2.0 (1.0 = normal).
#         filename: Optional output file name (saved in the output directory).
#         play: If true, stream each chunk to the speakers as soon as it is generated,
#             so long texts start playing almost immediately. Returns after playback ends.
#         save: If true (default), also write the audio to a WAV file. Set to false with
#             play=true for playback only.
#
#     Returns:
#         A short message with the absolute path of the generated file (if saved) and the duration.
#     """
#     text = text.strip()
#     if not text:
#         raise ValueError("text is empty")
#     if len(text) > MAX_CHARS:
#         raise ValueError(f"text is too long ({len(text)} chars, max {MAX_CHARS})")
#     if not play and not save:
#         raise ValueError("nothing to do: set play=true and/or save=true")
#
#     lang_code = voice[:1].lower()
#     if lang_code not in LANGUAGES:
#         raise ValueError(f"unknown voice '{voice}'. Call list_voices for valid IDs.")
#     speed = min(max(speed, 0.5), 2.0)
#
#     pipeline = _get_pipeline(lang_code)
#     player = _StreamPlayer() if play else None
#     chunks: list[np.ndarray] = []
#     try:
#         for _graphemes, _phonemes, audio in pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+"):
#             if audio is None:
#                 continue
#             chunk = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
#             chunks.append(chunk)
#             if player:
#                 player.feed(chunk)
#     finally:
#         if player:
#             player.close()  # blocks until playback has finished
#
#     if not chunks:
#         raise RuntimeError("Kokoro produced no audio for this text")
#
#     waveform = np.concatenate(chunks)
#     duration = len(waveform) / SAMPLE_RATE
#     played = " Played on speakers." if play else ""
#
#     if not save:
#         return f"Generated {duration:.1f}s of audio (not saved).{played}"
#
#     OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
#     out_path = OUTPUT_DIR / _safe_filename(filename)
#     sf.write(out_path, waveform, SAMPLE_RATE)
#     log.info("Wrote %s (%.1fs)", out_path, duration)
#     return f"Saved {duration:.1f}s of audio to {out_path.resolve()}.{played}"
#
#
# @mcp.tool()
# def play_file(path: str, wait: bool = True) -> str:
#     """Play an existing WAV file on the local speakers.
#
#     Args:
#         path: Path to a .wav file. A bare file name is looked up in the output directory.
#         wait: If true (default), return after playback finishes; if false, return immediately
#             and let it play in the background (a later play_file call replaces it).
#     """
#     file = Path(path).expanduser()
#     if not file.is_absolute() and not file.exists():
#         file = OUTPUT_DIR / file
#     file = file.resolve()
#     if file.suffix.lower() != ".wav":
#         raise ValueError("only .wav files are supported")
#     if not file.is_file():
#         raise FileNotFoundError(f"no such file: {file}")
#
#     if sys.platform == "win32":
#         import winsound
#
#         flags = winsound.SND_FILENAME | (0 if wait else winsound.SND_ASYNC)
#         winsound.PlaySound(str(file), flags)
#     else:
#         import sounddevice as sd
#
#         data, rate = sf.read(file, dtype="float32")
#         sd.play(data, rate)
#         if wait:
#             sd.wait()
#     return f"Played {file}" if wait else f"Started playing {file}"


def _status_text(session: _SpeechSession | None) -> str:
    if session is None:
        return "idle: no speech has been started"
    if session.state == "error":
        return f"error: {session.error}"
    return session.state


@mcp.tool()
def start_speech(text: str, voice: str = DEFAULT_VOICE, speed: float = 1.0) -> str:
    """Start speaking text aloud on the local speakers and return immediately.

    The speech runs in the background and can be controlled with pause_speech, resume_speech
    and stop_speech; check progress with speech_status. Audio is generated and played entirely
    in memory (nothing is written to disk). Starting a new speech stops any speech in progress.

    Args:
        text: The text to speak (plain text only, not a file path or URL).
        voice: Kokoro voice ID, e.g. "af_heart", "bm_george", "ff_siwis". The first letter
            selects the language (see list_voices).
        speed: Speaking rate, 0.5-2.0 (1.0 = normal).
    """
    global _session
    text = text.strip()
    if not text:
        raise ValueError("text is empty")
    if len(text) > MAX_CHARS:
        raise ValueError(f"text is too long ({len(text)} chars, max {MAX_CHARS})")
    if voice[:1].lower() not in LANGUAGES:
        raise ValueError(f"unknown voice '{voice}'. Call list_voices for valid IDs.")
    speed = min(max(speed, 0.5), 2.0)

    with _session_lock:
        previous = _session
        if previous is not None:
            previous.stop()
            previous.join(2.0)
        _session = _SpeechSession(text, voice, speed)
    return (
        f"Speech started ({len(text)} characters, voice {voice}). "
        "Use pause_speech / resume_speech / stop_speech to control it."
    )


@mcp.tool()
def pause_speech() -> str:
    """Pause the current speech. Playback holds within about 0.1 s; resume_speech continues from that point."""
    with _session_lock:
        session = _session
    if session is None or not session.pause():
        return f"Nothing to pause (status: {_status_text(session)})."
    return "Speech paused."


@mcp.tool()
def resume_speech() -> str:
    """Continue a paused speech from where it was paused."""
    with _session_lock:
        session = _session
    if session is None or not session.resume():
        return f"Nothing to resume (status: {_status_text(session)})."
    return "Speech resumed."


@mcp.tool()
def stop_speech() -> str:
    """Stop (interrupt) the current speech, playing or paused, and discard the rest of the text."""
    with _session_lock:
        session = _session
    if session is None or not session.stop():
        return f"Nothing to stop (status: {_status_text(session)})."
    return "Speech stopped."


@mcp.tool()
def speech_status() -> str:
    """Report the speech state: idle, playing, paused, finished, stopped or error."""
    with _session_lock:
        return _status_text(_session)


@mcp.tool()
def list_voices() -> dict[str, list[str]]:
    """List Kokoro voice IDs grouped by language. Prefix: af/am = US female/male, bf/bm = UK, etc."""
    return {LANGUAGES[code]: voices for code, voices in VOICES.items()}


if __name__ == "__main__":
    mcp.run()  # stdio transport
