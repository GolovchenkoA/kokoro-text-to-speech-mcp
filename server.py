"""Text-to-speech MCP server: wires the components together and runs the server over stdio."""

from __future__ import annotations

import logging
import signal
import sys
import threading
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer

from tts_mcp.catalog import load_catalog
from tts_mcp.config import Settings
from tts_mcp.detectors import LanguageDetector, LinguaDetector, lingua_is_installed
from tts_mcp.guards import GuardedSpeech, LanguageGuard
from tts_mcp.instance import InstanceManager
from mcp_tools import register_tools

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class App:
    mcp: MCPServer
    manager: InstanceManager
    detector: LanguageDetector | None = None  # None: texts are not checked for their language


def _language_detector(settings: Settings, detector: LanguageDetector | None) -> LanguageDetector | None:
    if not settings.language_check:
        return None
    if detector is not None:
        return detector
    if lingua_is_installed():
        return LinguaDetector()
    log.warning("The language check is off: install lingua-language-detector to turn it on")
    return None


def build_app(settings: Settings, pid: int | None = None, detector: LanguageDetector | None = None) -> App:
    """Create the components and register the tools (does not start anything).

    The tools talk to the speech backend through `GuardedSpeech`, which checks the language of a text
    before `start_speech` reaches the backend. A `detector` can be passed in (tests do).
    """
    catalog = load_catalog(settings.resolved_models_file)  # fails fast with a clear message
    manager = InstanceManager(settings, catalog, pid)
    detector = _language_detector(settings, detector)
    speech = manager if detector is None else GuardedSpeech(manager, [LanguageGuard(catalog, detector)])
    mcp = MCPServer("tts")
    register_tools(mcp, speech, catalog, settings.is_voice_control_enabled)
    return App(mcp=mcp, manager=manager, detector=detector)


def _exit_on_termination_signals() -> None:
    """Turn SIGTERM / Ctrl+Break into a normal exit so the shutdown in main() runs."""
    for name in ("SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, lambda _signum, _frame: sys.exit(0))


def main() -> None:
    # stdout is the MCP transport: all logging must go to stderr.
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    _exit_on_termination_signals()
    app = build_app(Settings.from_env())
    try:
        app.manager.activate()  # become the primary instance or join it as a secondary
        if app.detector is not None:  # loading the detector takes seconds: do it before the first request
            threading.Thread(target=app.detector.warm_up, name="tts-detector-warmup", daemon=True).start()
        app.mcp.run()  # stdio transport; returns when the client closes the pipe
    finally:
        app.manager.shutdown()  # stop speech, listener and endpoint


if __name__ == "__main__":
    main()
