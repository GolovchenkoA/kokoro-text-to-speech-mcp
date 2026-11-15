"""Unit tests for the energy gate (no threads, no fakes)."""

from __future__ import annotations

import numpy as np

from tts_mcp.config import Settings
from tts_mcp.voice_control.vad import VAD_HANGOVER_BLOCKS, VAD_PREROLL_BLOCKS, EnergyGate, make_gate


def block(amplitude: int) -> bytes:
    return np.full(1600, amplitude, dtype=np.int16).tobytes()


QUIET, LOUD = block(0), block(2000)


def test_silence_is_dropped():
    gate = EnergyGate(threshold=500)
    assert all(gate.process(QUIET) == ([], False) for _ in range(20))


def test_speech_opens_the_gate_and_releases_the_preroll():
    gate = EnergyGate(threshold=500)
    marked = [block(i + 1) for i in range(5)]  # quiet blocks (amplitude < threshold), distinguishable
    for b in marked:
        gate.process(b)
    fed, ended = gate.process(LOUD)
    assert fed == [*marked[-VAD_PREROLL_BLOCKS:], LOUD]  # only the most recent pre-roll blocks
    assert not ended


def test_hangover_then_close_and_reopen():
    gate = EnergyGate(threshold=500)
    gate.process(LOUD)
    results = [gate.process(QUIET) for _ in range(VAD_HANGOVER_BLOCKS)]
    assert [fed for fed, _ in results] == [[QUIET]] * VAD_HANGOVER_BLOCKS  # still fed during hangover
    assert [ended for _, ended in results] == [False] * (VAD_HANGOVER_BLOCKS - 1) + [True]
    assert gate.process(QUIET) == ([], False)  # closed again
    assert gate.process(LOUD)[0][-1] == LOUD  # and reopens


def test_speech_during_the_hangover_keeps_the_gate_open():
    gate = EnergyGate(threshold=500)
    gate.process(LOUD)
    for _ in range(VAD_HANGOVER_BLOCKS - 1):
        gate.process(QUIET)
    gate.process(LOUD)  # resets the silence counter
    results = [gate.process(QUIET) for _ in range(VAD_HANGOVER_BLOCKS - 1)]
    assert not any(ended for _, ended in results)


def test_empty_block_is_silence():
    assert EnergyGate(threshold=500).process(b"") == ([], False)


def test_make_gate_follows_settings():
    assert make_gate(Settings(vad_mode="off")) is None
    gate = make_gate(Settings(vad_threshold=123.0))
    assert gate is not None and gate.threshold == 123.0
