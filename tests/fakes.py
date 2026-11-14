"""In-process fakes for the audio device, Kokoro and Vosk so the tests need no hardware or models."""

from __future__ import annotations

import json
import queue
import threading
import time
import types

import numpy as np

CHUNK_FRAMES = 12_000  # 0.5 s at 24 kHz = 10 playback slices of 50 ms
WRITE_DELAY = 0.003  # seconds per slice written, so playback takes a measurable time


class FakeOutputStream:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.frames = 0
        self.started = self.stopped = self.aborted = self.closed = False

    def start(self) -> None:
        self.started = True

    def write(self, data) -> None:
        time.sleep(WRITE_DELAY)
        self.frames += len(data)

    def stop(self) -> None:
        self.stopped = True

    def abort(self) -> None:
        self.aborted = True

    def close(self) -> None:
        self.closed = True


class FakeMic:
    """Microphone fed by the test: queue bytes with say(); None ends the loop with an error."""

    def __init__(self) -> None:
        self.queue: queue.Queue[bytes | None] = queue.Queue()

    def say(self, phrase: str) -> None:
        self.queue.put(phrase.encode())

    def hang_up(self) -> None:
        self.queue.put(None)

    def __enter__(self) -> "FakeMic":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self, frames: int):
        item = self.queue.get(timeout=5)
        if item is None:
            raise RuntimeError("microphone closed")
        return item, False


class FakeSoundDevice(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("sounddevice")
        self.streams: list[FakeOutputStream] = []
        self.mic = FakeMic()
        self.mic_kwargs: dict | None = None
        self.played: list[tuple[int, int]] = []  # (frames, samplerate) per sd.play call

    def OutputStream(self, **kwargs) -> FakeOutputStream:  # noqa: N802 (mirrors sounddevice API)
        stream = FakeOutputStream(**kwargs)
        self.streams.append(stream)
        return stream

    def RawInputStream(self, **kwargs) -> FakeMic:  # noqa: N802
        self.mic_kwargs = kwargs
        return self.mic

    def play(self, data, samplerate) -> None:
        self.played.append((len(data), samplerate))

    def wait(self) -> None:
        return None


class FakeKokoro(types.ModuleType):
    """Fake `kokoro` module. Each non-empty line of text becomes one audio chunk."""

    def __init__(self) -> None:
        super().__init__("kokoro")
        self.calls: list[dict] = []
        calls = self.calls

        class KPipeline:
            def __init__(self, lang_code: str, repo_id: str, **kwargs) -> None:
                self.lang_code = lang_code

            def __call__(self, text, voice, speed, split_pattern=None):
                calls.append({"lang": self.lang_code, "text": text, "voice": voice, "speed": speed})
                if "BOOM" in text:
                    raise RuntimeError("synthesis failed")
                for line in text.split("\n"):
                    if line.strip():
                        yield line, "phonemes", np.full(CHUNK_FRAMES, 0.1, dtype=np.float32)

        self.KPipeline = KPipeline


class FakeVosk(types.ModuleType):
    """Fake `vosk` module: the 'audio' is the spoken phrase itself, recognized verbatim."""

    def __init__(self) -> None:
        super().__init__("vosk")
        self.model_args: list[dict] = []
        self.grammars: list[list[str]] = []
        vosk = self

        class Model:
            def __init__(self, model_path=None, lang=None) -> None:
                vosk.model_args.append({"model_path": model_path, "lang": lang})

        class KaldiRecognizer:
            def __init__(self, model, rate: int, grammar: str) -> None:
                self.rate = rate
                vosk.grammars.append(json.loads(grammar))
                self._heard = ""

            def AcceptWaveform(self, data: bytes) -> bool:  # noqa: N802
                self._heard = data.decode()
                return True

            def Result(self) -> str:  # noqa: N802
                return json.dumps({"text": self._heard})

            def Reset(self) -> None:  # noqa: N802
                self._heard = ""

        self.Model = Model
        self.KaldiRecognizer = KaldiRecognizer
        self.SetLogLevel = lambda level: None


def wait_until(condition, timeout: float = 5.0, interval: float = 0.01) -> bool:
    """Poll until condition() is truthy; return whether it became true within timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return bool(condition())


def thread_names() -> set[str]:
    return {t.name for t in threading.enumerate()}
