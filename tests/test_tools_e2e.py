"""End-to-end tests of the MCP tools: real MCP client <-> server, fake audio device and speech engine."""

from __future__ import annotations

import time

import pytest

from tts_mcp.config import MAX_CHARS, SAMPLE_RATE
from mcp_tools import speech_started_message
from tests.conftest import call_tool_on, long_text
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


# -- speak-last-reply prompt -----------------------------------------------------------------
def test_speak_last_reply_prompt_is_listed_with_a_messages_argument(list_prompts):
    prompts = {p.name: p for p in list_prompts()}
    assert set(prompts) == {"speak-last-reply"}
    prompt = prompts["speak-last-reply"]
    assert "previous answer" in prompt.description
    assert [(a.name, a.required) for a in prompt.arguments] == [("messages", False)]
    assert "last 5 messages" in prompt.arguments[0].description


def test_by_default_only_the_last_message_is_read(get_prompt_text):
    text = get_prompt_text("speak-last-reply")
    assert '"the last message"' in text
    assert "The last message is your previous assistant message" in text


@pytest.mark.parametrize("description", ["last 5 messages", "last fifth messages", "the last three"])
def test_the_requested_range_is_passed_to_the_model(get_prompt_text, description):
    text = get_prompt_text("speak-last-reply", messages=description)
    assert text.startswith(f'Read aloud this part of the conversation: "{description}".')


def test_blank_messages_argument_falls_back_to_the_default(get_prompt_text):
    assert '"the last message"' in get_prompt_text("speak-last-reply", messages="   ")


def test_prompt_tells_the_model_to_send_messages_unchanged_in_one_call(get_prompt_text):
    text = get_prompt_text("speak-last-reply", messages="last 5 messages")
    assert "`start_speech`" in text and "once" in text  # one call: a second call would cut the first off
    assert "exactly as written" in text and "character for character" in text
    assert "do not summarize" in text and "rephrase" in text and "add anything" in text
    assert "chronological order, oldest first" in text
    assert "only action is the tool call" in text  # no commentary around the call
    assert "no such messages" in text  # nothing to speak: do not call the tool


def test_prompt_defines_what_a_message_is(get_prompt_text):
    text = get_prompt_text("speak-last-reply", messages="last 2 messages")
    assert "either one the user sent or one the assistant (you) sent" in text
    assert "each counts separately" in text  # a message is not a question/answer pair
    assert "last fifth messages" in text  # ordinals count as numbers
    assert "Do not count this request itself" in text


def test_prompt_labels_the_owner_of_each_message_when_several_are_read(get_prompt_text):
    text = get_prompt_text("speak-last-reply", messages="last 5 messages")
    assert "`User message:`" in text and "`Assistant message:`" in text
    assert "own paragraph" in text
    assert "exactly one message is read, send it without a label" in text


def test_prompt_adds_no_limits(get_prompt_text):
    text = get_prompt_text("speak-last-reply", messages="last 100 messages").lower()
    assert "limit" not in text and "20,000" not in text and "at most" not in text


def test_tool_description_requires_verbatim_text_and_keeping_labels(list_tools):
    tool = next(t for t in list_tools() if t.name == "start_speech")
    assert "verbatim" in tool.description
    assert "Never summarize" in tool.description
    assert "previous answer" in tool.description
    assert '"User message:"' in tool.description and '"Assistant message:"' in tool.description


def test_list_voices_groups_by_language(call_tool):
    result = call_tool("list_voices")
    assert not result.is_error
    for language in ("American English", "British English", "Mandarin Chinese"):
        assert language in result.text
    assert "af_heart" in result.text


# -- start_speech result: how to control the speech ----------------------------------------
def test_start_speech_result_explains_how_to_pause_continue_and_stop(call_tool):
    text = call_tool("start_speech", text=long_text(40)).text
    assert text.startswith("Speech started (")
    for tool_name in ("pause_speech", "resume_speech", "stop_speech", "speech_status"):
        assert tool_name in text
    assert "pause the speech" in text and "continue the speech" in text and "stop the speech" in text
    assert "Voice control" not in text  # voice control is off in this app: do not advertise it


def test_start_speech_result_lists_voice_commands_when_voice_control_is_on(make_app, fakes):
    app = make_app(is_voice_control_enabled=True)
    assert wait_until(lambda: fakes.sd.mic_kwargs is not None)
    text = call_tool_on(app, "start_speech", text="Hello").text
    fakes.sd.mic.hang_up()
    assert 'Voice control is on: say "pause speech", "continue speech", "stop speech", "status speech".' in text


def test_started_message_format():
    assert speech_started_message(120, "af_heart", is_voice_control_enabled=False).splitlines() == [
        "Speech started (120 characters, voice af_heart). It plays in the background.",
        "Control it:",
        "- pause: ask me to pause the speech (tool pause_speech)",
        "- continue: ask me to continue the speech (tool resume_speech)",
        "- stop: ask me to stop the speech (tool stop_speech)",
        "- state: speech_status",
    ]


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


def test_voice_and_speed_are_passed_to_the_engine(call_tool, fakes):
    call_tool("start_speech", text="Bonjour", voice="ff_siwis", speed=1.3)
    assert wait_until(lambda: fakes.engine.calls)
    call = fakes.engine.calls[0]
    assert (call["lang"], call["voice"], call["speed"]) == ("f", "ff_siwis", 1.3)


def test_speed_is_clamped(call_tool, fakes):
    call_tool("start_speech", text="Hi", speed=9)
    assert wait_until(lambda: fakes.engine.calls)
    assert fakes.engine.calls[0]["speed"] == 2.0


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
