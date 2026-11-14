"""End-to-end tests of microphone voice control, driven by a scripted fake microphone and Vosk."""

from __future__ import annotations

import json
import threading

import pytest

import server
from tests.conftest import long_text
from tests.fakes import thread_names, wait_until

PHRASES = ["pause speech", "continue speech", "stop speech", "status speech"]


@pytest.fixture
def voice_loop(fakes):
    """Run the real voice-control loop in a thread; the test 'speaks' through fakes.sd.mic."""
    thread = threading.Thread(target=server._voice_control_loop, daemon=True)
    thread.start()
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None), "voice loop did not open the microphone"
    yield thread
    fakes.sd.mic.hang_up()
    thread.join(5)


@pytest.fixture
def speaking(call_tool, fakes):
    """A long speech that is playing when the test starts."""
    call_tool("start_speech", text=long_text(40))
    assert wait_until(lambda: server._session is not None and server._session.state == "playing")
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[0].frames > 0)
    return server._session


def state() -> str:
    return server._session.state


# -- setup ---------------------------------------------------------------------------------------
def test_recognizer_is_restricted_to_the_four_phrases(fakes, voice_loop):
    assert fakes.vosk.grammars == [[*PHRASES, "[unk]"]]
    assert fakes.vosk.model_args == [{"model_path": None, "lang": "en-us"}]
    assert fakes.sd.mic_kwargs["samplerate"] == server.MIC_RATE
    assert fakes.sd.mic_kwargs["dtype"] == "int16"


def test_local_model_and_microphone_can_be_configured(fakes, monkeypatch):
    monkeypatch.setenv("KOKORO_VOSK_MODEL", "/models/vosk-small")
    monkeypatch.setenv("KOKORO_MIC_DEVICE", "USB Mic")
    thread = threading.Thread(target=server._voice_control_loop, daemon=True)
    thread.start()
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.hang_up()
    thread.join(5)
    assert fakes.vosk.model_args == [{"model_path": "/models/vosk-small", "lang": None}]
    assert fakes.sd.mic_kwargs["device"] == "USB Mic"


def test_voice_control_is_off_by_default(fakes):
    server._start_voice_control()
    assert "kokoro-voice-control" not in thread_names()


def test_voice_control_starts_when_enabled(fakes, monkeypatch):
    monkeypatch.setenv("KOKORO_WAKEWORD", "1")
    server._start_voice_control()
    assert wait_until(lambda: "kokoro-voice-control" in thread_names())
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.hang_up()
    assert wait_until(lambda: "kokoro-voice-control" not in thread_names())


def test_loop_exits_cleanly_when_vosk_is_missing(fakes, monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "vosk", None)  # makes `import vosk` fail
    thread = threading.Thread(target=server._voice_control_loop, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive()  # logged the error instead of crashing the server


# -- commands ------------------------------------------------------------------------------------
def test_pause_continue_stop_by_voice(fakes, voice_loop, speaking):
    mic = fakes.sd.mic

    mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")

    mic.say("continue speech")
    assert wait_until(lambda: state() == "playing")

    mic.say("stop speech")
    assert wait_until(lambda: state() == "stopped")
    assert wait_until(lambda: fakes.sd.streams[0].aborted)


def test_status_speech_announces_the_state_aloud(fakes, voice_loop, speaking):
    fakes.sd.mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")

    fakes.sd.mic.say("status speech")
    assert wait_until(lambda: fakes.sd.played)

    announcement = fakes.kokoro.calls[-1]
    assert announcement["text"] == "Speech is paused."
    assert announcement["lang"] == "a"  # status is always announced in English
    assert fakes.sd.played[0][1] == server.SAMPLE_RATE
    assert state() == "paused"  # announcing does not change the speech state


def test_status_speech_with_no_speech_says_idle(fakes, voice_loop):
    fakes.sd.mic.say("status speech")
    assert wait_until(lambda: fakes.sd.played)
    assert fakes.kokoro.calls[-1]["text"] == "Speech is idle."


@pytest.mark.parametrize(
    "heard",
    ["hello world", "please pause speech now", "pause", "stop speech please", "", "[unk]", "PAUSE SPEECH"],
)
def test_only_exact_phrases_trigger_commands(fakes, voice_loop, speaking, heard):
    fakes.sd.mic.say(heard)
    fakes.sd.mic.hang_up()  # FIFO: the loop has processed the utterance above before it sees this
    voice_loop.join(5)
    assert not voice_loop.is_alive()
    assert state() == "playing"
    assert not fakes.sd.played  # and no status announcement either


def test_commands_without_active_speech_are_harmless(fakes, voice_loop):
    for phrase in ("pause speech", "continue speech", "stop speech"):
        fakes.sd.mic.say(phrase)
    fakes.sd.mic.say("status speech")  # still answered afterwards: the loop did not die
    assert wait_until(lambda: fakes.sd.played)
    assert voice_loop.is_alive()
    assert server._session is None


def test_voice_commands_can_only_control_speech(fakes, voice_loop, speaking):
    """The command table is the whole attack surface: four phrases, four fixed actions."""
    assert server.VOICE_COMMANDS == {
        "pause speech": "pause",
        "continue speech": "resume",
        "stop speech": "stop",
        "status speech": "status",
    }
    assert json.loads(json.dumps(fakes.vosk.grammars[0])) == [*PHRASES, "[unk]"]


# -- voice activity gate (VAD) -------------------------------------------------------------------
def test_silence_never_reaches_the_recognizer(fakes, voice_loop):
    fakes.sd.mic.silence(30)
    fakes.sd.mic.hang_up()
    voice_loop.join(5)
    assert fakes.vosk.accepted == 0  # the heavy stage did not run at all


def test_speech_opens_the_gate_with_preroll(fakes, voice_loop, speaking):
    fakes.sd.mic.silence(10)
    fakes.sd.mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")
    # Only the pre-roll plus the speech block were fed; the earlier silence was dropped.
    assert fakes.vosk.accepted == server.VAD_PREROLL_BLOCKS + 1


def test_gate_stays_open_for_the_hangover_then_closes(fakes, voice_loop):
    mic = fakes.sd.mic
    mic.say("hello world")
    mic.silence(server.VAD_HANGOVER_BLOCKS + 15)
    mic.hang_up()
    voice_loop.join(5)
    # speech block + hangover blocks were fed; the remaining silence was not
    assert fakes.vosk.accepted == 1 + server.VAD_HANGOVER_BLOCKS
    assert fakes.vosk.final_calls == 1  # utterance end flushes the recognizer exactly once


def test_gate_reopens_for_a_second_utterance(fakes, voice_loop, speaking):
    mic = fakes.sd.mic
    mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")
    mic.silence(server.VAD_HANGOVER_BLOCKS + 3)  # gate closes
    mic.say("continue speech")
    assert wait_until(lambda: state() == "playing")


def test_vad_off_feeds_every_block_to_the_recognizer(fakes, monkeypatch):
    monkeypatch.setenv("KOKORO_VAD", "off")
    thread = threading.Thread(target=server._voice_control_loop, daemon=True)
    thread.start()
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.silence(12)
    fakes.sd.mic.hang_up()
    thread.join(5)
    assert fakes.vosk.accepted == 12


def test_threshold_can_be_raised(fakes, monkeypatch, speaking):
    monkeypatch.setenv("KOKORO_VAD_THRESHOLD", "5000")  # louder than the fake speech (~1000)
    thread = threading.Thread(target=server._voice_control_loop, daemon=True)
    thread.start()
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.say("pause speech")
    fakes.sd.mic.hang_up()
    thread.join(5)
    assert fakes.vosk.accepted == 0
    assert state() == "playing"


def test_invalid_vad_settings_fall_back_to_defaults(fakes, monkeypatch):
    monkeypatch.setenv("KOKORO_VAD", "magic")
    monkeypatch.setenv("KOKORO_VAD_THRESHOLD", "loud")
    gate = server._make_gate()
    assert gate is not None and gate.threshold == server.DEFAULT_VAD_THRESHOLD
