"""MCP tool definitions. Thin adapters: validate nothing themselves, delegate to SpeechService."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from kokoro_mcp.speech import InvalidSpeechRequest, SpeechService
from kokoro_mcp.voices import voices_by_language


def register_tools(mcp: MCPServer, speech: SpeechService, default_voice: str) -> None:
    """Register all tools on `mcp`, bound to the given speech service."""

    @mcp.tool()
    def start_speech(text: str, voice: str = default_voice, speed: float = 1.0) -> str:
        """Start speaking text aloud on the local speakers and return immediately.

        The speech runs in the background and can be controlled with pause_speech, resume_speech
        and stop_speech; check progress with speech_status. Audio is generated and played entirely
        in memory (nothing is written to disk). Starting a new speech stops any speech in progress.

        Args:
            text: The text to speak (plain text only, not a file path or URL).
            voice: Kokoro voice ID, e.g. "af_heart", "bm_george", "ff_siwis". The first letter
                selects the language (see list_voices).
            speed: Speaking rate, 0.5-2.0 (1.0 = normal).
        """
        try:
            characters = speech.start(text, voice, speed)
        except InvalidSpeechRequest as exc:
            raise ToolError(str(exc)) from exc  # ToolError (not ValueError) so the model sees the reason
        return (
            f"Speech started ({characters} characters, voice {voice}). "
            "Use pause_speech / resume_speech / stop_speech to control it."
        )

    @mcp.tool()
    def pause_speech() -> str:
        """Pause the current speech. Playback holds within about 0.1 s; resume_speech continues from that point."""
        if not speech.pause():
            return f"Nothing to pause (status: {speech.describe()})."
        return "Speech paused."

    @mcp.tool()
    def resume_speech() -> str:
        """Continue a paused speech from where it was paused."""
        if not speech.resume():
            return f"Nothing to resume (status: {speech.describe()})."
        return "Speech resumed."

    @mcp.tool()
    def stop_speech() -> str:
        """Stop (interrupt) the current speech, playing or paused, and discard the rest of the text."""
        if not speech.stop():
            return f"Nothing to stop (status: {speech.describe()})."
        return "Speech stopped."

    @mcp.tool()
    def speech_status() -> str:
        """Report the speech state: idle, playing, paused, finished, stopped or error."""
        return speech.describe()

    @mcp.tool()
    def list_voices() -> dict[str, list[str]]:
        """List Kokoro voice IDs grouped by language. Prefix: af/am = US female/male, bf/bm = UK, etc."""
        return voices_by_language()
