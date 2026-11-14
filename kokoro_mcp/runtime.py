"""Everything the primary (or a standalone) instance runs: synthesis, speech, voice control, endpoint."""

from __future__ import annotations

import os
from multiprocessing.connection import Listener

from kokoro_mcp.config import Settings
from kokoro_mcp.ipc import PrimaryServer
from kokoro_mcp.speech import SpeechService
from kokoro_mcp.synthesis import SpeechSynthesizer
from kokoro_mcp.voice_control.announcer import StatusAnnouncer
from kokoro_mcp.voice_control.commands import VoiceCommandHandler
from kokoro_mcp.voice_control.listener import VoiceControlListener


class PrimaryRuntime:
    """The working side of the server. With an endpoint it also serves secondary instances."""

    def __init__(
        self,
        settings: Settings,
        pid: int | None = None,
        endpoint: tuple[Listener, str, bytes] | None = None,
    ) -> None:
        synthesizer = SpeechSynthesizer(settings.device)
        self.speech = SpeechService(synthesizer)
        handler = VoiceCommandHandler(self.speech, StatusAnnouncer(synthesizer))
        self.voice_control = VoiceControlListener(settings, handler)
        self._server: PrimaryServer | None = None
        if endpoint is not None:
            listener, address, authkey = endpoint
            self._server = PrimaryServer(listener, address, authkey, self.speech, pid or os.getpid())

    def start(self) -> None:
        if self._server is not None:
            self._server.start()
        self.voice_control.start()

    def stop(self) -> None:
        """Stop listening, release the endpoint and stop any speech."""
        self.voice_control.stop()
        if self._server is not None:
            self._server.close()
        self.speech.shutdown()
