"""MCP tool definitions. Thin adapters: validate nothing themselves, delegate to the speech backend."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from tts_mcp.catalog import Catalog
from tts_mcp.ipc import PrimaryUnavailable
from tts_mcp.speech import InvalidSpeechRequest, SpeechController
from tts_mcp.voice_control.commands import VOICE_COMMANDS


DEFAULT_MESSAGES = "the last message"

SPEAK_MESSAGES_PROMPT = (
    'Read aloud this part of the conversation: "{messages}".\n'
    "A message is one single message, either one the user sent or one the assistant (you) sent; "
    "each counts separately. The last message is your previous assistant message. "
    '"Last N messages" (N may be written as a number or a word, e.g. "last 5 messages" or '
    '"last fifth messages") means the N most recent messages counted back from it. '
    "Do not count this request itself, tool calls, tool results or system messages.\n"
    "Collect those messages in chronological order, oldest first, and call the `start_speech` tool "
    "once with them as the `text` argument. "
    "Copy every message exactly as written, character for character: do not summarize, shorten, "
    "translate, rephrase, reformat or add anything to it. "
    "If more than one message is read, put each message in its own paragraph (blank line between "
    "them) and start it with its owner label: `User message:` for a message the user sent, "
    "`Assistant message:` for a message the assistant sent. "
    "If exactly one message is read, send it without a label. "
    "Do not write any commentary, greeting or confirmation before or after the call: your only "
    "action is the tool call. "
    "If there are no such messages, say so instead of calling the tool."
)


def speech_started_message(characters: int, model: str, voice: str, is_voice_control_enabled: bool) -> str:
    """Result of start_speech: confirms the start and says how to pause, continue and stop."""
    lines = [
        f"Speech started ({characters} characters, model {model}, voice {voice}). It plays in the background.",
        "Control it:",
        "- pause: ask me to pause the speech (tool pause_speech)",
        "- continue: ask me to continue the speech (tool resume_speech)",
        "- stop: ask me to stop the speech (tool stop_speech)",
        "- state: speech_status",
    ]
    if is_voice_control_enabled:
        phrases = ", ".join(f'"{phrase}"' for phrase in VOICE_COMMANDS)
        lines.append(f"Voice control is on: say {phrases}.")
    return "\n".join(lines)


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Turn expected failures into ToolError (not ValueError/RuntimeError) so the model sees the reason."""
    try:
        yield
    except (InvalidSpeechRequest, PrimaryUnavailable) as exc:
        raise ToolError(str(exc)) from exc


def register_tools(
    mcp: MCPServer, speech: SpeechController, catalog: Catalog, is_voice_control_enabled: bool
) -> None:
    """Register all tools on `mcp`, bound to the given speech backend."""

    @mcp.tool()
    def start_speech(
        text: str,
        voice: str | None = None,
        speed: float = 1.0,
        model: str | None = None,
        language: str | None = None,
    ) -> str:
        """Start speaking text aloud on the local speakers and return immediately.

        The speech runs in the background and can be controlled with pause_speech, resume_speech
        and stop_speech; check progress with speech_status. Audio is generated and played entirely
        in memory (nothing is written to disk). Starting a new speech stops any speech in progress.

        The result confirms the start and tells how to pause, continue and stop the speech.

        Pass the text exactly as the user gave it or as it was written in the message to be read
        aloud: verbatim, character for character. Never summarize, shorten, translate, rephrase,
        reformat or add to it. To read your previous answer aloud, send that whole answer unchanged.
        If the text has owner labels such as "User message:" and "Assistant message:", keep them:
        they are spoken so the listener knows who said what.

        Args:
            text: The text to speak, exactly as it should be heard (plain text only, not a file
                path or URL).
            voice: Voice ID from list_models. Optional: leave it out to get the default voice for
                the language.
            speed: Speaking rate, 0.5-2.0 (1.0 = normal). Some models ignore it.
            model: Model name from list_models. Optional: leave it out to use the default model,
                or the first model that has the requested voice and language.
            language: Language code of the text, e.g. "en", "de", "fr", "ru" (see list_models). Always
                pass it when you know the language of the text: without it the default model's voice
                reads the text, and a Latin-script text in another language is then read wrongly.
                A text in another writing system (Cyrillic, Chinese, Korean, ...) is detected, and
                a voice that cannot read it is refused with an error.
        """
        with _tool_errors():
            started = speech.start(text, voice, speed, model, language)
        return speech_started_message(
            started["characters"], started["model"], started["voice"], is_voice_control_enabled
        )

    @mcp.prompt(
        name="speak-last-reply",
        description="Speak recent messages aloud, unchanged (default: your previous answer)",
    )
    def speak_last_reply(
        messages: Annotated[
            str, Field(description='Which messages to read, e.g. "last 5 messages". Default: the last message')
        ] = DEFAULT_MESSAGES,
    ) -> str:
        return SPEAK_MESSAGES_PROMPT.format(messages=messages.strip() or DEFAULT_MESSAGES)

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
    def list_models() -> dict:
        """List the text-to-speech models with the languages and voices of each, and the default model.

        Use it to pick a voice whose language matches the text, or to see which models can speak a
        language. Each language shows its default voice, used when start_speech gets none.
        """
        return catalog.describe()
