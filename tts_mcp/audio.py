"""Audio device access. `sounddevice` is imported lazily so the server starts without it."""

from __future__ import annotations

import numpy as np

from tts_mcp.config import MIC_RATE


def open_speaker_stream(sample_rate: int):
    """Open (not yet start) a mono float32 output stream at the given sample rate."""
    import sounddevice as sd

    return sd.OutputStream(samplerate=sample_rate, channels=1, dtype="float32")


def open_microphone(device: str | None):
    """Open a raw int16 input stream that delivers 100 ms blocks."""
    import sounddevice as sd

    return sd.RawInputStream(samplerate=MIC_RATE, blocksize=MIC_RATE // 10, dtype="int16", channels=1, device=device)


def play_blocking(samples: np.ndarray, sample_rate: int) -> None:
    """Play float samples on the default output device and wait until they finish."""
    import sounddevice as sd

    sd.play(samples.astype(np.float32), sample_rate)
    sd.wait()
