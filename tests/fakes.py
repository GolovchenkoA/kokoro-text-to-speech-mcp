"""In-process fakes for the audio device, the speech engine and Vosk so the tests need no hardware or models."""

from __future__ import annotations

import json
import queue
import threading
import time
import types

import numpy as np

SAMPLE_RATE = 24_000  # rate of the models in the default models.json
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
    """Microphone fed by the test with 100 ms int16 blocks.

    say(phrase) queues a loud block that encodes the phrase (amplitude 1000 + index into the
    shared phrase registry); silence(n) queues n silent blocks; hang_up() ends the loop with an error.
    """

    BLOCK_FRAMES = 1600
    BASE_AMPLITUDE = 1000

    def __init__(self, phrases: list[str]) -> None:
        self.queue: queue.Queue[bytes | None] = queue.Queue()
        self.phrases = phrases

    def say(self, phrase: str) -> None:
        self.phrases.append(phrase)
        amplitude = self.BASE_AMPLITUDE + len(self.phrases) - 1
        self.queue.put(np.full(self.BLOCK_FRAMES, amplitude, dtype=np.int16).tobytes())

    def silence(self, blocks: int = 1) -> None:
        for _ in range(blocks):
            self.queue.put(np.zeros(self.BLOCK_FRAMES, dtype=np.int16).tobytes())

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
    def __init__(self, phrases: list[str]) -> None:
        super().__init__("sounddevice")
        self.streams: list[FakeOutputStream] = []
        self.mic = FakeMic(phrases)
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


class FakeEngine(types.ModuleType):
    """Fake `kokoro` module. Each non-empty line of text becomes one audio chunk."""

    def __init__(self) -> None:
        super().__init__("kokoro")
        self.calls: list[dict] = []
        calls = self.calls

        class KPipeline:
            def __init__(self, lang_code: str, repo_id: str, **kwargs) -> None:
                self.lang_code = lang_code
                self.device = kwargs.get("device")

            def __call__(self, text, voice, speed, split_pattern=None):
                calls.append(
                    {"lang": self.lang_code, "text": text, "voice": voice, "speed": speed, "device": self.device}
                )
                if "BOOM" in text:
                    raise RuntimeError("synthesis failed")
                for line in text.split("\n"):
                    if line.strip():
                        yield line, "phonemes", np.full(CHUNK_FRAMES, 0.1, dtype=np.float32)

        self.KPipeline = KPipeline


class FakeTorch(types.ModuleType):
    """Fake `torch` module: just the dtypes the Qwen engine passes on."""

    def __init__(self) -> None:
        super().__init__("torch")
        self.bfloat16 = "bfloat16"
        self.float32 = "float32"


class FakeQwen(types.ModuleType):
    """Fake `qwen_tts` module. A piece of text becomes one waveform; `fail_on_gpu` makes loading on a GPU fail."""

    def __init__(self, rate: int = SAMPLE_RATE) -> None:
        super().__init__("qwen_tts")
        self.loads: list[dict] = []
        self.calls: list[dict] = []
        self.fail_on_gpu = False
        self.rate = rate
        outer = self

        class Qwen3TTSModel:
            @classmethod
            def from_pretrained(cls, repo, device_map, dtype):
                outer.loads.append({"repo": repo, "device_map": device_map, "dtype": dtype})
                if outer.fail_on_gpu and device_map != "cpu":
                    raise RuntimeError("CUDA out of memory")
                return cls()

            def generate_custom_voice(self, text, language, speaker):
                outer.calls.append({"text": text, "language": language, "speaker": speaker})
                if "BOOM" in text:
                    raise RuntimeError("synthesis failed")
                return [np.full(outer.rate // 2, 0.1, dtype=np.float32)], outer.rate

        self.Qwen3TTSModel = Qwen3TTSModel


class FakeVosk(types.ModuleType):
    """Fake `vosk` module. Loud blocks from FakeMic.say() are 'recognized' as their phrase;
    silent blocks recognize nothing. Counts how many blocks the recognizer actually received."""

    def __init__(self) -> None:
        super().__init__("vosk")
        self.model_args: list[dict] = []
        self.grammars: list[list[str]] = []
        self.phrases: list[str] = []
        self.accepted = 0  # blocks fed to AcceptWaveform
        self.final_calls = 0
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
                vosk.accepted += 1
                samples = np.frombuffer(data, dtype=np.int16)
                if not samples.any():
                    return False
                self._heard = vosk.phrases[int(samples[0]) - FakeMic.BASE_AMPLITUDE]
                return True

            def Result(self) -> str:  # noqa: N802
                return json.dumps({"text": self._heard})

            def FinalResult(self) -> str:  # noqa: N802
                vosk.final_calls += 1
                return json.dumps({"text": ""})

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


class EchoEngine:
    """A speech engine that exists only in a test's models file: proves a model is added by config alone."""

    created: list[tuple[str, str | None]] = []
    calls: list[dict] = []

    def __init__(self, spec, device) -> None:
        EchoEngine.created.append((spec.id, device))

    def synthesize(self, text, voice, language, speed):
        EchoEngine.calls.append({"text": text, "voice": voice, "language": language})
        yield np.full(CHUNK_FRAMES // 2, 0.1, dtype=np.float32)
