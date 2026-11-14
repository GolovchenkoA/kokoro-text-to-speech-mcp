"""Kokoro TTS MCP server.

Exposes tools to Claude Desktop over stdio:
  - start_speech(text, voice, speed) -> speak text in the background (in memory, no files)
  - pause_speech() / resume_speech() / stop_speech() / speech_status() -> control it
  - list_voices() -> available voice IDs grouped by language
Optional (KOKORO_WAKEWORD=1): microphone commands "pause speech", "continue speech",
"stop speech", "status speech" that control the current speech and nothing else.
"""

from __future__ import annotations

import logging
import os
import queue
import sys
import threading

import numpy as np
from mcp.server.mcpserver import MCPServer

# stdout is the MCP transport — all logging must go to stderr.
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kokoro-mcp")

SAMPLE_RATE = 24_000
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


# --------------------------------------------------------------------------------------------
# Optional voice control (KOKORO_WAKEWORD=1): listens on the microphone for four fixed phrases
# and can only pause / resume / stop the current speech or announce its status. Audio is
# processed in memory, never stored or sent anywhere.
# --------------------------------------------------------------------------------------------
MIC_RATE = 16_000
VOICE_COMMANDS = {
    "pause speech": "pause",
    "continue speech": "resume",
    "stop speech": "stop",
    "status speech": "status",
}


def _announce(message: str) -> None:
    """Speak a short English phrase on a separate stream (used for 'status speech')."""
    import sounddevice as sd

    chunks = []
    for _g, _p, audio in _get_pipeline("a")(message, voice="af_heart", speed=1.0):
        if audio is not None:
            chunks.append(audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio))
    if chunks:
        sd.play(np.concatenate(chunks).astype(np.float32), SAMPLE_RATE)
        sd.wait()


def _run_voice_command(action: str) -> None:
    log.info("Voice command: %s", action)
    if action == "pause":
        pause_speech()
    elif action == "resume":
        resume_speech()
    elif action == "stop":
        stop_speech()
    elif action == "status":
        with _session_lock:
            state = _session.state if _session is not None else "idle"
        _announce(f"Speech is {state}.")


def _voice_control_loop() -> None:
    """Background thread: recognize the fixed command phrases from the microphone."""
    try:
        import json

        import sounddevice as sd
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model_path = os.environ.get("KOKORO_VOSK_MODEL")
        # Without a path, vosk downloads the small English model (~40 MB) to ~/.cache/vosk on first use.
        model = Model(model_path=model_path) if model_path else Model(lang="en-us")
        grammar = json.dumps([*VOICE_COMMANDS, "[unk]"])  # restrict recognition to the four phrases
        recognizer = KaldiRecognizer(model, MIC_RATE, grammar)
        device = os.environ.get("KOKORO_MIC_DEVICE") or None
        with sd.RawInputStream(
            samplerate=MIC_RATE, blocksize=MIC_RATE // 10, dtype="int16", channels=1, device=device
        ) as mic:
            log.info("Voice control on: say %s", ", ".join(f"'{p}'" for p in VOICE_COMMANDS))
            while True:
                data, _overflowed = mic.read(MIC_RATE // 10)
                if recognizer.AcceptWaveform(bytes(data)):
                    text = json.loads(recognizer.Result()).get("text", "").strip()
                    # Act only when the whole utterance is exactly a command, so speech
                    # picked up from the speakers or a room is very unlikely to trigger it.
                    if text in VOICE_COMMANDS:
                        _run_voice_command(VOICE_COMMANDS[text])
                        recognizer.Reset()
    except Exception:
        log.exception("Voice control stopped (is `vosk` installed and a microphone available?)")


def _start_voice_control() -> None:
    if os.environ.get("KOKORO_WAKEWORD", "").lower() in ("1", "true", "yes", "on"):
        threading.Thread(target=_voice_control_loop, name="kokoro-voice-control", daemon=True).start()


if __name__ == "__main__":
    _start_voice_control()
    mcp.run()  # stdio transport
