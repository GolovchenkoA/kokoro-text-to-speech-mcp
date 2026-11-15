"""The voice command table and the handler that carries commands out."""

from __future__ import annotations

import logging

from tts_mcp.speech import SpeechService
from tts_mcp.voice_control.announcer import StatusAnnouncer

log = logging.getLogger(__name__)

# The whole attack surface of voice control: four phrases, four fixed actions.
VOICE_COMMANDS = {
    "pause speech": "pause",
    "continue speech": "resume",
    "stop speech": "stop",
    "status speech": "status",
}


class VoiceCommandHandler:
    """Maps a recognized phrase to an action on the current speech. Nothing else can be triggered."""

    def __init__(self, speech: SpeechService, announcer: StatusAnnouncer) -> None:
        self._speech = speech
        self._announcer = announcer
        self._actions = {
            "pause": speech.pause,
            "resume": speech.resume,
            "stop": speech.stop,
            "status": self._announce_status,
        }

    def handle(self, phrase: str) -> bool:
        """Run the command for an exact phrase. Returns False if the phrase is not a command."""
        action = VOICE_COMMANDS.get(phrase)
        if action is None:
            return False
        log.info("Voice command: %s", action)
        self._actions[action]()
        return True

    def _announce_status(self) -> None:
        self._announcer.announce(f"Speech is {self._speech.state_label()}.")
