"""Background speech: `SpeechSession` plays one text, `SpeechService` owns the active session."""

from __future__ import annotations

import enum
import logging
import queue
import threading
from collections.abc import Callable
from typing import Protocol

import numpy as np

from tts_mcp.audio import open_speaker_stream
from tts_mcp.config import MAX_CHARS, SAMPLE_RATE
from tts_mcp.synthesis import SpeechSynthesizer
from tts_mcp.voices import language_code

log = logging.getLogger(__name__)

SLICE_FRAMES = SAMPLE_RATE // 20  # 50 ms: granularity of pause/stop while audio is playing
LOOKAHEAD_CHUNKS = 3  # bounds how far synthesis runs ahead of playback (matters while paused)
JOIN_TIMEOUT = 2.0


class SpeechState(enum.StrEnum):
    PLAYING = "playing"
    PAUSED = "paused"
    FINISHED = "finished"
    STOPPED = "stopped"
    ERROR = "error"


ACTIVE_STATES = (SpeechState.PLAYING, SpeechState.PAUSED)


class InvalidSpeechRequest(ValueError):
    """The text, voice or speed of a speech request is not acceptable."""


class AudioStream(Protocol):
    def start(self) -> None: ...
    def write(self, data: np.ndarray) -> object: ...
    def stop(self) -> None: ...
    def abort(self) -> None: ...
    def close(self) -> None: ...


class SpeechController(Protocol):
    """What the tools need from a speech backend: the local service or a forwarder to the primary."""

    def start(self, text: str, voice: str, speed: float) -> int: ...
    def pause(self) -> bool: ...
    def resume(self) -> bool: ...
    def stop(self) -> bool: ...
    def describe(self) -> str: ...
    def state_label(self) -> str: ...
    def shutdown(self) -> None: ...


class SpeechSession:
    """One in-memory speech: a generator thread synthesizes chunks into a bounded queue and a
    playback thread streams them to the speakers in 50 ms slices. Nothing is written to disk.

    State: playing <-> paused, then finished | stopped | error
    """

    def __init__(
        self,
        text: str,
        voice: str,
        speed: float,
        synthesizer: SpeechSynthesizer,
        open_stream: Callable[[], AudioStream] = open_speaker_stream,
    ) -> None:
        self.state = SpeechState.PLAYING
        self.error: str | None = None
        self._text, self._voice, self._speed = text, voice, speed
        self._synthesizer = synthesizer
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=LOOKAHEAD_CHUNKS)
        self._stop = threading.Event()
        self._running = threading.Event()  # set = playing, cleared = paused
        self._running.set()
        # Open in the caller's thread so a missing/busy audio device fails fast.
        self._stream = open_stream()
        self._generator = threading.Thread(target=self._generate, name="tts-generate", daemon=True)
        self._player = threading.Thread(target=self._play, name="tts-play", daemon=True)
        self._generator.start()
        self._player.start()

    # -- controls ---------------------------------------------------------------------------
    def pause(self) -> bool:
        if self.state != SpeechState.PLAYING:
            return False
        self._running.clear()
        self.state = SpeechState.PAUSED
        return True

    def resume(self) -> bool:
        if self.state != SpeechState.PAUSED:
            return False
        self.state = SpeechState.PLAYING
        self._running.set()
        return True

    def stop(self) -> bool:
        if self.state not in ACTIVE_STATES:
            return False
        self.state = SpeechState.STOPPED
        self._stop.set()
        self._running.set()  # wake the player if it is paused
        return True

    def join(self, timeout: float) -> None:
        self._player.join(timeout)

    # -- worker threads -----------------------------------------------------------------------
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
        if self.state in ACTIVE_STATES:
            self.state = SpeechState.ERROR
        self._stop.set()
        self._running.set()

    def _generate(self) -> None:
        try:
            produced = False
            for chunk in self._synthesizer.synthesize(self._text, self._voice, self._speed):
                if self._stop.is_set():
                    return
                produced = True
                if not self._put(chunk):
                    return
            if not produced:
                raise RuntimeError("The speech model produced no audio for this text")
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
                if self.state in ACTIVE_STATES:
                    self.state = SpeechState.FINISHED
        except BaseException as exc:
            self._fail(exc)
        finally:
            try:
                self._stream.close()
            except Exception:
                pass


class SpeechService:
    """Validates requests and keeps the single active `SpeechSession`."""

    def __init__(
        self,
        synthesizer: SpeechSynthesizer,
        open_stream: Callable[[], AudioStream] = open_speaker_stream,
    ) -> None:
        self._synthesizer = synthesizer
        self._open_stream = open_stream
        self._lock = threading.Lock()
        self._session: SpeechSession | None = None

    @property
    def current_session(self) -> SpeechSession | None:
        with self._lock:
            return self._session

    def start(self, text: str, voice: str, speed: float) -> int:
        """Start speaking, stopping any speech in progress. Returns the number of characters spoken."""
        text = text.strip()
        if not text:
            raise InvalidSpeechRequest("text is empty")
        if len(text) > MAX_CHARS:
            raise InvalidSpeechRequest(f"text is too long ({len(text)} chars, max {MAX_CHARS})")
        if language_code(voice) is None:
            raise InvalidSpeechRequest(f"unknown voice '{voice}'. Call list_voices for valid IDs.")
        speed = min(max(speed, 0.5), 2.0)

        with self._lock:
            previous = self._session
            if previous is not None:
                previous.stop()
                previous.join(JOIN_TIMEOUT)
            self._session = SpeechSession(text, voice, speed, self._synthesizer, self._open_stream)
        return len(text)

    def pause(self) -> bool:
        session = self.current_session
        return session is not None and session.pause()

    def resume(self) -> bool:
        session = self.current_session
        return session is not None and session.resume()

    def stop(self) -> bool:
        session = self.current_session
        return session is not None and session.stop()

    def state_label(self) -> str:
        """Short state name: 'idle' when nothing was started, else the session state."""
        session = self.current_session
        return "idle" if session is None else session.state.value

    def describe(self) -> str:
        """Human-readable status for tool responses."""
        session = self.current_session
        if session is None:
            return "idle: no speech has been started"
        if session.state == SpeechState.ERROR:
            return f"error: {session.error}"
        return session.state.value

    def shutdown(self) -> None:
        """Stop the current speech and wait briefly for its playback thread."""
        session = self.current_session
        if session is not None:
            session.stop()
            session.join(JOIN_TIMEOUT)
