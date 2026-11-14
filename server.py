"""Kokoro TTS MCP server: wires the components together and runs the server over stdio."""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer

from kokoro_mcp.config import Settings
from kokoro_mcp.speech import SpeechService
from kokoro_mcp.synthesis import SpeechSynthesizer
from kokoro_mcp.voice_control.announcer import StatusAnnouncer
from kokoro_mcp.voice_control.commands import VoiceCommandHandler
from kokoro_mcp.voice_control.listener import VoiceControlListener
from mcp_tools import register_tools


@dataclass(frozen=True)
class App:
    mcp: MCPServer
    speech: SpeechService
    voice_control: VoiceControlListener


def build_app(settings: Settings) -> App:
    """Create all components and register the tools (does not start anything)."""
    synthesizer = SpeechSynthesizer(settings.device)
    speech = SpeechService(synthesizer)
    handler = VoiceCommandHandler(speech, StatusAnnouncer(synthesizer))
    mcp = MCPServer("kokoro-tts")
    register_tools(mcp, speech, settings.default_voice)
    return App(mcp=mcp, speech=speech, voice_control=VoiceControlListener(settings, handler))


def main() -> None:
    # stdout is the MCP transport: all logging must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = build_app(Settings.from_env())
    app.voice_control.start()
    app.mcp.run()  # stdio transport


if __name__ == "__main__":
    main()
