"""End-to-end tests of the MCP tools: real MCP client <-> server, fake audio device and Kokoro."""

from __future__ import annotations

import time

from kokoro_mcp.config import MAX_CHARS, SAMPLE_RATE
from tests.conftest import long_text
from tests.fakes import CHUNK_FRAMES, wait_until

EXPECTED_TOOLS = {"start_speech", "pause_speech", "resume_speech", "stop_speech", "speech_status", "list_voices"}


def status(call_tool) -> str:
    return call_tool("speech_status").text


def current_stream(fakes):
    assert wait_until(lambda: fakes.sd.streams), "no audio stream was opened"
    return fakes.sd.streams[-1]


# -- tool catalogue --------------------------------------------------------------------------
def test_server_exposes_exactly_the_expected_tools(list_tools):
    names = {tool.name for tool in list_tools()}
    assert names == EXPECTED_TOOLS  # speak / play_file stay removed


def test_start_speech_accepts_text_only(list_tools):
    tool = next(t for t in list_tools() if t.name == "start_speech")
    properties = set(tool.input_schema["properties"])
    assert properties == {"text", "voice", "speed"}  # no path / url / file parameters
    assert tool.input_schema["required"] == ["text"]


def test_list_voices_groups_by_language(call_tool):
    result = call_tool("list_voices")
    assert not result.is_error
    for language in ("American English", "British English", "Mandarin Chinese"):
        assert language in result.text
    assert "af_heart" in result.text


# -- start / finish ----------------------------------------------------------------------------
def test_status_is_idle_before_any_speech(call_tool):
    assert status(call_tool).startswith("idle")


def test_start_speech_plays_in_memory_and_finishes(call_tool, fakes):
    result = call_tool("start_speech", text=long_text(6), voice="af_heart", speed=1.0)
    assert not result.is_error
    assert result.text.startswith("Speech started")

    assert wait_until(lambda: status(call_tool) == "finished")
    stream = current_stream(fakes)
    assert stream.started and stream.stopped and stream.closed
    assert not stream.aborted  # finished normally: buffered audio was allowed to drain
    assert stream.frames == 6 * CHUNK_FRAMES  # every generated chunk reached the speakers
    assert stream.kwargs["samplerate"] == SAMPLE_RATE
    assert list(fakes.workdir.iterdir()) == []  # nothing was written to disk


def test_start_speech_returns_before_playback_ends(call_tool, fakes):
    started = time.monotonic()
    call_tool("start_speech", text=long_text(40))
    assert time.monotonic() - started < 2.0  # non-blocking: ~40 chunks take far longer to play
    assert status(call_tool) in ("playing", "finished")
    assert status(call_tool) != "finished"


def test_voice_and_speed_are_passed_to_kokoro(call_tool, fakes):
    call_tool("start_speech", text="Bonjour", voice="ff_siwis", speed=1.3)
    assert wait_until(lambda: fakes.kokoro.calls)
    call = fakes.kokoro.calls[0]
    assert (call["lang"], call["voice"], call["speed"]) == ("f", "ff_siwis", 1.3)


def test_speed_is_clamped(call_tool, fakes):
    call_tool("start_speech", text="Hi", speed=9)
    assert wait_until(lambda: fakes.kokoro.calls)
    assert fakes.kokoro.calls[0]["speed"] == 2.0


# -- pause / resume / stop -------------------------------------------------------------------
def test_pause_holds_playback_and_resume_continues(call_tool, fakes):
    call_tool("start_speech", text=long_text(40))
    stream = current_stream(fakes)
    assert wait_until(lambda: stream.frames > 0)

    assert call_tool("pause_speech").text == "Speech paused."
    assert status(call_tool) == "paused"
    time.sleep(0.15)  # let the slice that was already in flight finish
    held = stream.frames
    time.sleep(0.3)
    assert stream.frames == held  # nothing is written while paused

    assert call_tool("resume_speech").text == "Speech resumed."
    assert status(call_tool) == "playing"
    assert wait_until(lambda: stream.frames > held)


def test_stop_interrupts_and_discards_the_rest(call_tool, fakes):
    call_tool("start_speech", text=long_text(40))
    stream = current_stream(fakes)
    assert wait_until(lambda: stream.frames > 0)

    assert call_tool("stop_speech").text == "Speech stopped."
    assert status(call_tool) == "stopped"
    assert wait_until(lambda: stream.closed)
    assert stream.aborted  # buffered audio dropped immediately
    time.sleep(0.2)
    assert stream.frames < 40 * CHUNK_FRAMES
    assert status(call_tool) == "stopped"


def test_stop_works_while_paused(call_tool, fakes):
    call_tool("start_speech", text=long_text(40))
    stream = current_stream(fakes)
    assert wait_until(lambda: stream.frames > 0)
    call_tool("pause_speech")

    assert call_tool("stop_speech").text == "Speech stopped."
    assert wait_until(lambda: stream.closed)
    assert stream.aborted


def test_controls_without_active_speech_report_nothing_to_do(call_tool):
    assert call_tool("pause_speech").text.startswith("Nothing to pause")
    assert call_tool("resume_speech").text.startswith("Nothing to resume")
    assert call_tool("stop_speech").text.startswith("Nothing to stop")


def test_resume_and_double_pause_are_rejected_in_the_wrong_state(call_tool, fakes):
    call_tool("start_speech", text=long_text(40))
    assert call_tool("resume_speech").text.startswith("Nothing to resume")  # already playing
    call_tool("pause_speech")
    assert call_tool("pause_speech").text.startswith("Nothing to pause")  # already paused


def test_controls_after_finish_report_nothing_to_do(call_tool):
    call_tool("start_speech", text="Short.")
    assert wait_until(lambda: status(call_tool) == "finished")
    assert call_tool("pause_speech").text.startswith("Nothing to pause")
    assert call_tool("stop_speech").text.startswith("Nothing to stop")


def test_starting_a_new_speech_stops_the_previous_one(call_tool, fakes):
    call_tool("start_speech", text=long_text(40))
    first = current_stream(fakes)
    assert wait_until(lambda: first.frames > 0)

    call_tool("start_speech", text=long_text(3))
    assert wait_until(lambda: first.closed)
    assert first.aborted
    assert wait_until(lambda: status(call_tool) == "finished")
    assert len(fakes.sd.streams) == 2


# -- validation and failures -----------------------------------------------------------------
def test_empty_text_is_rejected(call_tool):
    result = call_tool("start_speech", text="   ")
    assert result.is_error and "empty" in result.text


def test_unknown_voice_is_rejected(call_tool):
    result = call_tool("start_speech", text="Hello", voice="xx_nobody")
    assert result.is_error and "unknown voice" in result.text


def test_too_long_text_is_rejected(call_tool):
    result = call_tool("start_speech", text="a" * (MAX_CHARS + 1))
    assert result.is_error and "too long" in result.text


def test_synthesis_failure_is_reported_in_status(call_tool, fakes):
    assert not call_tool("start_speech", text="BOOM").is_error  # returns immediately, fails in background
    assert wait_until(lambda: status(call_tool).startswith("error"))
    assert "synthesis failed" in status(call_tool)
    assert wait_until(lambda: current_stream(fakes).closed)
