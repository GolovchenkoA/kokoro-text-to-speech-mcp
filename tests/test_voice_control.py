"""End-to-end tests of microphone voice control, driven by a scripted fake microphone and Vosk."""

from __future__ import annotations

import json
import sys
import threading

import pytest

from tts_mcp.config import MIC_RATE, Settings
from tts_mcp.voice_control.commands import VOICE_COMMANDS
from tts_mcp.voice_control.listener import THREAD_NAME
from tts_mcp.voice_control.vad import VAD_HANGOVER_BLOCKS, VAD_PREROLL_BLOCKS
from server import build_app
from tests.conftest import begin_speech
from tests.fakes import SAMPLE_RATE, thread_names, wait_until

PHRASES = ["pause speech", "continue speech", "stop speech", "status speech"]


def listener(app):
    return app.manager.runtime.voice_control


def run_loop(voice_listener) -> threading.Thread:
    thread = threading.Thread(target=voice_listener.run, daemon=True)
    thread.start()
    return thread


def stop_loop(fakes, thread) -> None:
    fakes.sd.mic.hang_up()
    thread.join(5)


@pytest.fixture
def voice_loop(fakes, app):
    """Run the real voice-control loop in a thread; the test 'speaks' through fakes.sd.mic."""
    thread = run_loop(listener(app))
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None), "voice loop did not open the microphone"
    yield thread
    stop_loop(fakes, thread)


@pytest.fixture
def speaking(app, fakes):
    """A long speech that is playing when the test starts."""
    return begin_speech(app, fakes)


@pytest.fixture
def state(app):
    """Callable returning the current speech state."""
    return lambda: app.manager.runtime.speech.current_session.state


# -- setup ---------------------------------------------------------------------------------------
def test_recognizer_is_restricted_to_the_four_phrases(fakes, voice_loop):
    assert fakes.vosk.grammars == [[*PHRASES, "[unk]"]]
    assert fakes.vosk.model_args == [{"model_path": None, "lang": "en-us"}]
    assert fakes.sd.mic_kwargs["samplerate"] == MIC_RATE
    assert fakes.sd.mic_kwargs["dtype"] == "int16"


def test_local_model_and_microphone_can_be_configured(fakes, make_app):
    app = make_app(vosk_model="/models/vosk-small", mic_device="USB Mic")
    thread = run_loop(listener(app))
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    stop_loop(fakes, thread)
    assert fakes.vosk.model_args == [{"model_path": "/models/vosk-small", "lang": None}]
    assert fakes.sd.mic_kwargs["device"] == "USB Mic"


def test_voice_control_listens_by_default(fakes):
    """With no TTS_VOICE_CONTROL_ENABLED set, an activated instance starts the microphone listener."""
    app = build_app(Settings.from_env({"TTS_IPC_DIR": str(fakes.tmp_path / "ipc")}))
    try:
        app.manager.activate()
        assert wait_until(lambda: THREAD_NAME in thread_names())
        assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
        fakes.sd.mic.hang_up()
    finally:
        app.manager.shutdown()


def test_voice_control_can_be_turned_off(fakes):
    """TTS_VOICE_CONTROL_ENABLED=0: no listener thread and the microphone is never opened."""
    env = {"TTS_IPC_DIR": str(fakes.tmp_path / "ipc"), "TTS_VOICE_CONTROL_ENABLED": "0"}
    app = build_app(Settings.from_env(env))
    try:
        app.manager.activate()
        assert listener(app).start() is None
        assert THREAD_NAME not in thread_names()
        assert fakes.sd.mic_kwargs is None
    finally:
        app.manager.shutdown()


def test_voice_control_starts_when_enabled(fakes, make_app):
    make_app(is_voice_control_enabled=True)  # activating the instance starts the listener
    assert wait_until(lambda: THREAD_NAME in thread_names())
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.hang_up()
    assert wait_until(lambda: THREAD_NAME not in thread_names())


def test_loop_exits_cleanly_when_vosk_is_missing(fakes, app, monkeypatch):
    monkeypatch.setitem(sys.modules, "vosk", None)  # makes `import vosk` fail
    thread = run_loop(listener(app))
    thread.join(5)
    assert not thread.is_alive()  # logged the error instead of crashing the server


# -- commands ------------------------------------------------------------------------------------
def test_pause_continue_stop_by_voice(fakes, voice_loop, speaking, state):
    mic = fakes.sd.mic

    mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")

    mic.say("continue speech")
    assert wait_until(lambda: state() == "playing")

    mic.say("stop speech")
    assert wait_until(lambda: state() == "stopped")
    assert wait_until(lambda: fakes.sd.streams[0].aborted)


def test_status_speech_announces_the_state_aloud(fakes, voice_loop, speaking, state):
    fakes.sd.mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")

    fakes.sd.mic.say("status speech")
    assert wait_until(lambda: fakes.sd.played)

    announcement = fakes.engine.calls[-1]
    assert announcement["text"] == "Speech is paused."
    assert announcement["lang"] == "a"  # status is always announced in English
    assert fakes.sd.played[0][1] == SAMPLE_RATE
    assert state() == "paused"  # announcing does not change the speech state


def test_status_speech_with_no_speech_says_idle(fakes, voice_loop):
    fakes.sd.mic.say("status speech")
    assert wait_until(lambda: fakes.sd.played)
    assert fakes.engine.calls[-1]["text"] == "Speech is idle."


@pytest.mark.parametrize(
    "heard",
    ["hello world", "please pause speech now", "pause", "stop speech please", "", "[unk]", "PAUSE SPEECH"],
)
def test_only_exact_phrases_trigger_commands(fakes, voice_loop, speaking, state, heard):
    fakes.sd.mic.say(heard)
    fakes.sd.mic.hang_up()  # FIFO: the loop has processed the utterance above before it sees this
    voice_loop.join(5)
    assert not voice_loop.is_alive()
    assert state() == "playing"
    assert not fakes.sd.played  # and no status announcement either


def test_commands_without_active_speech_are_harmless(fakes, app, voice_loop):
    for phrase in ("pause speech", "continue speech", "stop speech"):
        fakes.sd.mic.say(phrase)
    fakes.sd.mic.say("status speech")  # still answered afterwards: the loop did not die
    assert wait_until(lambda: fakes.sd.played)
    assert voice_loop.is_alive()
    assert app.manager.runtime.speech.current_session is None


def test_voice_commands_can_only_control_speech(fakes, voice_loop):
    """The command table is the whole attack surface: four phrases, four fixed actions."""
    assert VOICE_COMMANDS == {
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


def test_speech_opens_the_gate_with_preroll(fakes, voice_loop, speaking, state):
    fakes.sd.mic.silence(10)
    fakes.sd.mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")
    # Only the pre-roll plus the speech block were fed; the earlier silence was dropped.
    assert fakes.vosk.accepted == VAD_PREROLL_BLOCKS + 1


def test_gate_stays_open_for_the_hangover_then_closes(fakes, voice_loop):
    mic = fakes.sd.mic
    mic.say("hello world")
    mic.silence(VAD_HANGOVER_BLOCKS + 15)
    mic.hang_up()
    voice_loop.join(5)
    # speech block + hangover blocks were fed; the remaining silence was not
    assert fakes.vosk.accepted == 1 + VAD_HANGOVER_BLOCKS
    assert fakes.vosk.final_calls == 1  # utterance end flushes the recognizer exactly once


def test_gate_reopens_for_a_second_utterance(fakes, voice_loop, speaking, state):
    mic = fakes.sd.mic
    mic.say("pause speech")
    assert wait_until(lambda: state() == "paused")
    mic.silence(VAD_HANGOVER_BLOCKS + 3)  # gate closes
    mic.say("continue speech")
    assert wait_until(lambda: state() == "playing")


def test_vad_off_feeds_every_block_to_the_recognizer(fakes, make_app):
    app = make_app(vad_mode="off")
    thread = run_loop(listener(app))
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.silence(12)
    stop_loop(fakes, thread)
    assert fakes.vosk.accepted == 12


def test_threshold_can_be_raised(fakes, make_app):
    app = make_app(vad_threshold=5000.0)  # louder than the fake speech (~1000)
    session = begin_speech(app, fakes)
    thread = run_loop(listener(app))
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.say("pause speech")
    stop_loop(fakes, thread)
    assert fakes.vosk.accepted == 0
    assert session.state == "playing"
