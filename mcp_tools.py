"""MCP tool definitions. Thin adapters: validate nothing themselves, delegate to the speech backend."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from kokoro_mcp.ipc import PrimaryUnavailable
from kokoro_mcp.speech import InvalidSpeechRequest, SpeechController
from kokoro_mcp.voices import voices_by_language


SPEAK_LAST_REPLY_PROMPT = (
    "Take your previous assistant message, exactly as written, character for character, and call "
    "the `start_speech` tool once with it as the `text` argument. "
    "Do not summarize, shorten, translate, rephrase, reformat or add anything to it. "
    "Do not write any commentary, greeting or confirmation before or after the call: your only "
    "action is the tool call. "
    "If there is no previous assistant message, say so instead of calling the tool."
)


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Turn expected failures into ToolError (not ValueError/RuntimeError) so the model sees the reason."""
    try:
        yield
    except (InvalidSpeechRequest, PrimaryUnavailable) as exc:
        raise ToolError(str(exc)) from exc


def register_tools(mcp: MCPServer, speech: SpeechController, default_voice: str) -> None:
    """Register all tools on `mcp`, bound to the given speech backend."""

    @mcp.tool()
    def start_speech(text: str, voice: str = default_voice, speed: float = 1.0) -> str:
        """Start speaking text aloud on the local speakers and return immediately.

        The speech runs in the background and can be controlled with pause_speech, resume_speech
        and stop_speech; check progress with speech_status. Audio is generated and played entirely
        in memory (nothing is written to disk). Starting a new speech stops any speech in progress.

        Pass the text exactly as the user gave it or as it was written in the message to be read
        aloud: verbatim, character for character. Never summarize, shorten, translate, rephrase,
        reformat or add to it. To read your previous answer aloud, send that whole answer unchanged.

        Args:
            text: The text to speak, exactly as it should be heard (plain text only, not a file
                path or URL).
            voice: Kokoro voice ID, e.g. "af_heart", "bm_george", "ff_siwis". The first letter
                selects the language (see list_voices).
            speed: Speaking rate, 0.5-2.0 (1.0 = normal).
        """
        with _tool_errors():
            characters = speech.start(text, voice, speed)
        return (
            f"Speech started ({characters} characters, voice {voice}). "
            "Use pause_speech / resume_speech / stop_speech to control it."
        )

    @mcp.prompt(name="speak-last-reply", description="Speak your previous answer aloud, unchanged")
    def speak_last_reply() -> str:
        return SPEAK_LAST_REPLY_PROMPT

    @mcp.tool()
    def pause_speech() -> str:
        """Pause the current speech. Playback holds within about 0.1 s; resume_speech continues from that point."""
        with _tool_errors():
            if not speech.pause():
                return f"Nothing to pause (status: {speech.describe()})."
        return "Speech paused."

    @mcp.tool()
    def resume_speech() -> str:
        """Continue a paused speech from where it was paused."""
        with _tool_errors():
            if not speech.resume():
                return f"Nothing to resume (status: {speech.describe()})."
        return "Speech resumed."

    @mcp.tool()
    def stop_speech() -> str:
        """Stop (interrupt) the current speech, playing or paused, and discard the rest of the text."""
        with _tool_errors():
            if not speech.stop():
                return f"Nothing to stop (status: {speech.describe()})."
        return "Speech stopped."

    @mcp.tool()
    def speech_status() -> str:
        """Report the speech state: idle, playing, paused, finished, stopped or error."""
        with _tool_errors():
            return speech.describe()

    @mcp.tool()
    def list_voices() -> dict[str, list[str]]:
        """List Kokoro voice IDs grouped by language. Prefix: af/am = US female/male, bf/bm = UK, etc."""
        return voices_by_language()
