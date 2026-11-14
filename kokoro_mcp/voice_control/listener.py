"""Background thread that listens on the microphone for the voice commands."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable

from kokoro_mcp.audio import open_microphone
from kokoro_mcp.config import MIC_RATE, Settings
from kokoro_mcp.voice_control.commands import VOICE_COMMANDS, VoiceCommandHandler
from kokoro_mcp.voice_control.vad import EnergyGate, make_gate

log = logging.getLogger(__name__)

THREAD_NAME = "kokoro-voice-control"


class VoiceControlListener:
    """Microphone -> VAD gate -> Vosk (restricted to the command phrases) -> command handler."""

    def __init__(
        self,
        settings: Settings,
        handler: VoiceCommandHandler,
        gate_factory: Callable[[Settings], EnergyGate | None] = make_gate,
    ) -> None:
        self._settings = settings
        self._handler = handler
        self._gate_factory = gate_factory

    def start(self) -> threading.Thread | None:
        """Start listening in a daemon thread if voice control is enabled."""
        if not self._settings.voice_control:
            return None
        thread = threading.Thread(target=self.run, name=THREAD_NAME, daemon=True)
        thread.start()
        return thread

    def run(self) -> None:
        """Blocking listen loop. Logs and returns if the microphone or Vosk is unavailable."""
        try:
            self._listen()
        except Exception:
            log.exception("Voice control stopped (is `vosk` installed and a microphone available?)")

    def _listen(self) -> None:
        from vosk import KaldiRecognizer, Model, SetLogLevel

        SetLogLevel(-1)
        model_path = self._settings.vosk_model
        # Without a path, vosk downloads the small English model (~40 MB) to ~/.cache/vosk on first use.
        model = Model(model_path=model_path) if model_path else Model(lang="en-us")
        grammar = json.dumps([*VOICE_COMMANDS, "[unk]"])  # restrict recognition to the four phrases
        recognizer = KaldiRecognizer(model, MIC_RATE, grammar)
        gate = self._gate_factory(self._settings)

        with open_microphone(self._settings.mic_device) as mic:
            log.info("Voice control on: say %s", ", ".join(f"'{p}'" for p in VOICE_COMMANDS))
            log.info("Voice activity gate: %s", f"energy (threshold {gate.threshold:g})" if gate else "off")
            while True:
                data, _overflowed = mic.read(MIC_RATE // 10)
                blocks, ended = gate.process(bytes(data)) if gate else ([bytes(data)], False)
                for block in blocks:
                    if recognizer.AcceptWaveform(block):
                        self._dispatch(recognizer, recognizer.Result())
                if ended:  # speech stopped: flush whatever the recognizer still holds
                    self._dispatch(recognizer, recognizer.FinalResult())

    def _dispatch(self, recognizer, result_json: str) -> None:
        # Act only when the whole utterance is exactly a command, so speech picked up from the
        # speakers or a room is very unlikely to trigger it.
        text = json.loads(result_json).get("text", "").strip()
        if self._handler.handle(text):
            recognizer.Reset()
