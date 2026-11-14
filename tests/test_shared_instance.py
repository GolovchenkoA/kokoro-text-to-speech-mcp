"""Tests of the primary/secondary instances: one backend shared by every server copy."""

from __future__ import annotations

import logging
import threading
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client

import pytest

from kokoro_mcp import ipc
from kokoro_mcp.ipc import PrimaryUnavailable, RemoteSpeechService
from kokoro_mcp.voice_control.listener import THREAD_NAME
from tests.conftest import begin_speech, call_tool_on, long_text
from tests.fakes import wait_until

PRIMARY_PID, SECONDARY_PID = 1111, 2222


@pytest.fixture
def pair(make_app):
    primary = make_app(pid=PRIMARY_PID)
    secondary = make_app(pid=SECONDARY_PID)
    return primary, secondary


def status(app) -> str:
    return call_tool_on(app, "speech_status").text


def session(primary):
    return primary.manager.runtime.speech.current_session


def listener_threads() -> int:
    return sum(1 for t in threading.enumerate() if t.name == THREAD_NAME)


# -- roles -------------------------------------------------------------------------------------
def test_first_instance_is_primary_and_the_next_is_secondary(pair):
    primary, secondary = pair
    assert primary.manager.role == "primary" and primary.manager.runtime is not None
    assert secondary.manager.role == "secondary" and secondary.manager.runtime is None


def test_shared_instance_can_be_disabled(make_app):
    first = make_app(shared_instance=False)
    second = make_app(shared_instance=False)
    assert first.manager.role == second.manager.role == "primary"
    assert first.manager.runtime is not second.manager.runtime


# -- speech goes through the primary -------------------------------------------------------------
def test_speech_started_on_a_secondary_plays_on_the_primary(pair, fakes):
    primary, secondary = pair
    result = call_tool_on(secondary, "start_speech", text=long_text(40))
    assert not result.is_error and result.text.startswith("Speech started")

    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[0].frames > 0)
    assert len(fakes.sd.streams) == 1  # one speech, one audio stream, whichever instance asked
    assert session(primary).state == "playing"
    assert status(secondary) == status(primary) == "playing"


def test_controls_work_from_either_instance(pair, fakes):
    primary, secondary = pair
    call_tool_on(secondary, "start_speech", text=long_text(40))
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[0].frames > 0)

    assert call_tool_on(secondary, "pause_speech").text == "Speech paused."
    assert session(primary).state == "paused"
    assert status(primary) == "paused"

    assert call_tool_on(primary, "resume_speech").text == "Speech resumed."
    assert status(secondary) == "playing"

    assert call_tool_on(secondary, "stop_speech").text == "Speech stopped."
    assert session(primary).state == "stopped"
    assert wait_until(lambda: fakes.sd.streams[0].aborted)


def test_a_new_speech_from_the_other_instance_replaces_the_current_one(pair, fakes):
    primary, secondary = pair
    call_tool_on(primary, "start_speech", text=long_text(40))
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[0].frames > 0)

    call_tool_on(secondary, "start_speech", text=long_text(3))
    assert wait_until(lambda: fakes.sd.streams[0].aborted)
    assert wait_until(lambda: status(secondary) == "finished")


def test_validation_errors_reach_the_model_through_a_secondary(pair):
    _, secondary = pair
    empty = call_tool_on(secondary, "start_speech", text="  ")
    assert empty.is_error and "empty" in empty.text
    voice = call_tool_on(secondary, "start_speech", text="Hi", voice="xx_nobody")
    assert voice.is_error and "unknown voice" in voice.text


def test_only_the_primary_loads_the_models(pair, fakes):
    primary, secondary = pair
    call_tool_on(secondary, "start_speech", text="Hello")
    assert wait_until(lambda: fakes.kokoro.calls)
    assert len(fakes.kokoro.calls) == 1  # synthesized once, in the primary
    assert secondary.manager.runtime is None  # the secondary has no synthesizer, speech or listener


# -- logging -------------------------------------------------------------------------------------
def test_redirected_speech_is_logged_with_both_process_ids(make_app, caplog):
    caplog.set_level(logging.INFO)
    make_app(pid=PRIMARY_PID)
    secondary = make_app(pid=SECONDARY_PID)

    call_tool_on(secondary, "start_speech", text="Hello")

    messages = [r.getMessage() for r in caplog.records]
    assert f"Instance process {PRIMARY_PID} is the primary" in messages
    assert (
        f"Instance process {SECONDARY_PID} is a secondary: speech is redirected to process {PRIMARY_PID} (primary)"
        in messages
    )
    assert (
        f"Speech redirected from process {SECONDARY_PID} (secondary) to process {PRIMARY_PID} (primary): start"
        in messages
    )
    assert f"Speech request 'start' received from process {SECONDARY_PID} (secondary)" in messages


# -- one voice listener --------------------------------------------------------------------------
def test_only_the_primary_listens_and_answers(make_app, fakes):
    make_app(pid=PRIMARY_PID, voice_control=True)
    secondary = make_app(pid=SECONDARY_PID, voice_control=True)
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    assert listener_threads() == 1  # not one per instance
    assert secondary.manager.runtime is None

    fakes.sd.mic.say("status speech")
    assert wait_until(lambda: fakes.sd.played)
    time.sleep(0.3)
    assert len(fakes.sd.played) == 1  # a single answer
    fakes.sd.mic.hang_up()


def test_voice_commands_control_speech_started_through_a_secondary(make_app, fakes):
    primary = make_app(pid=PRIMARY_PID, voice_control=True)
    secondary = make_app(pid=SECONDARY_PID, voice_control=True)
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    call_tool_on(secondary, "start_speech", text=long_text(40))
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[0].frames > 0)

    fakes.sd.mic.say("pause speech")
    assert wait_until(lambda: status(secondary) == "paused")
    assert session(primary).state == "paused"
    fakes.sd.mic.hang_up()


# -- lifecycle -----------------------------------------------------------------------------------
def test_a_secondary_takes_over_when_the_primary_goes_away(pair, fakes):
    primary, secondary = pair
    primary.manager.shutdown()

    result = call_tool_on(secondary, "start_speech", text=long_text(40))
    assert not result.is_error
    assert secondary.manager.role == "primary"
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[-1].frames > 0)
    assert status(secondary) == "playing"


def test_the_new_primary_serves_later_instances(pair, make_app, fakes):
    primary, secondary = pair
    primary.manager.shutdown()
    call_tool_on(secondary, "speech_status")  # triggers the takeover

    third = make_app(pid=3333)
    assert third.manager.role == "secondary"
    call_tool_on(third, "start_speech", text=long_text(40))
    assert wait_until(lambda: secondary.manager.runtime.speech.current_session is not None)


def test_takeover_starts_voice_control_in_the_new_primary(make_app, fakes):
    primary = make_app(pid=PRIMARY_PID, voice_control=True)
    secondary = make_app(pid=SECONDARY_PID, voice_control=True)
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    fakes.sd.mic.hang_up()  # the old listener ends with its microphone
    primary.manager.shutdown()
    assert wait_until(lambda: listener_threads() == 0)

    call_tool_on(secondary, "speech_status")  # takeover
    assert secondary.manager.role == "primary"
    assert wait_until(lambda: listener_threads() == 1)
    fakes.sd.mic.hang_up()


def test_shutdown_stops_speech_listener_and_endpoint(make_app, fakes):
    app = make_app(pid=PRIMARY_PID, voice_control=True)
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    begin_speech(app, fakes)
    fakes.sd.mic.hang_up()

    app.manager.shutdown()

    assert fakes.sd.streams[0].aborted  # speech stopped
    assert wait_until(lambda: listener_threads() == 0)  # background listener gone
    assert app.manager.role is None
    successor = make_app(pid=4444)  # the endpoint was released
    assert successor.manager.role == "primary"


def test_shutdown_is_idempotent(pair):
    primary, secondary = pair
    for app in (secondary, primary):
        app.manager.shutdown()
        app.manager.shutdown()


# -- security and plumbing ------------------------------------------------------------------------
def test_connections_with_the_wrong_key_are_rejected(pair, fakes):
    primary, secondary = pair
    address = ipc.endpoint_address(fakes.tmp_path / "ipc")
    with pytest.raises(AuthenticationError):
        Client(address, family=ipc.FAMILY, authkey=b"x" * ipc.KEY_BYTES)
    assert status(secondary) == "idle: no speech has been started"  # the endpoint keeps serving


def test_authkey_is_created_once_and_reused(tmp_path):
    first = ipc.load_authkey(tmp_path / "ipc")
    assert len(first) == ipc.KEY_BYTES
    assert ipc.load_authkey(tmp_path / "ipc") == first
    assert ipc.load_authkey(tmp_path / "other") != first


def test_a_damaged_key_file_is_replaced(tmp_path, monkeypatch):
    (tmp_path / "ipc").mkdir()
    (tmp_path / "ipc" / "ipc.key").write_bytes(b"short")
    clock = iter(range(0, 1000, 10))  # jump past the 2 s wait for a half-written key
    monkeypatch.setattr(ipc.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(ipc.time, "sleep", lambda _s: None)
    assert len(ipc.load_authkey(tmp_path / "ipc")) == ipc.KEY_BYTES


def test_each_ipc_directory_has_its_own_endpoint(tmp_path):
    assert ipc.endpoint_address(tmp_path / "a") == ipc.endpoint_address(tmp_path / "a")
    assert ipc.endpoint_address(tmp_path / "a") != ipc.endpoint_address(tmp_path / "b")


# -- robustness ------------------------------------------------------------------------------------
def test_shutting_down_the_primary_never_hangs(make_app, fakes):
    """Regression: close() used to deadlock when its wake-up connection arrived after the accept
    thread had exited (the throw-away client waited forever for an authentication challenge)."""
    for round_number in range(15):
        ipc_dir = fakes.tmp_path / f"ipc-{round_number}"
        primary = make_app(pid=PRIMARY_PID, ipc_dir=ipc_dir)
        secondary = make_app(pid=SECONDARY_PID, ipc_dir=ipc_dir)
        assert status(secondary).startswith("idle")  # the secondary holds an open connection
        started = time.monotonic()
        primary.manager.shutdown()
        assert time.monotonic() - started < 3.0
        secondary.manager.shutdown()


def silent_primary(tmp_path, answer_hello: bool):
    """A fake primary that accepts connections but never answers requests."""
    ipc_dir = tmp_path / "silent"
    key = ipc.load_authkey(ipc_dir)
    address = ipc.endpoint_address(ipc_dir)
    listener = ipc.open_listener(address, key)

    def serve():
        conn = listener.accept()
        if answer_hello:
            conn.recv_bytes()
            conn.send_bytes(b'{"ok": true, "result": {"primary_pid": 1}}')
        time.sleep(5)  # then say nothing

    threading.Thread(target=serve, daemon=True).start()
    return RemoteSpeechService(address, key, SECONDARY_PID), listener


def test_a_primary_that_stops_answering_does_not_hang_the_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "REQUEST_TIMEOUT", 0.3)
    remote, listener = silent_primary(tmp_path, answer_hello=True)
    remote.connect()
    started = time.monotonic()
    with pytest.raises(PrimaryUnavailable):
        remote.describe()
    assert time.monotonic() - started < 3.0
    listener.close()


def test_a_primary_that_never_greets_does_not_hang_the_caller(tmp_path, monkeypatch):
    monkeypatch.setattr(ipc, "CONNECT_TIMEOUT", 0.3)
    remote, listener = silent_primary(tmp_path, answer_hello=False)
    started = time.monotonic()
    with pytest.raises(PrimaryUnavailable):
        remote.connect()
    assert time.monotonic() - started < 3.0
    listener.close()
