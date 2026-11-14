"""Kokoro TTS MCP server: wires the components together and runs the server over stdio."""

from __future__ import annotations

import logging
import signal
import sys
from dataclasses import dataclass

from mcp.server.mcpserver import MCPServer

from kokoro_mcp.config import Settings
from kokoro_mcp.instance import InstanceManager
from mcp_tools import register_tools


@dataclass(frozen=True)
class App:
    mcp: MCPServer
    manager: InstanceManager


def build_app(settings: Settings, pid: int | None = None) -> App:
    """Create the components and register the tools (does not start anything)."""
    manager = InstanceManager(settings, pid)
    mcp = MCPServer("kokoro-tts")
    register_tools(mcp, manager, settings.default_voice, settings.is_voice_control_enabled)
    return App(mcp=mcp, manager=manager)


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
        app.mcp.run()  # stdio transport; returns when the client closes the pipe
    finally:
        app.manager.shutdown()  # stop speech, listener and endpoint


if __name__ == "__main__":
    main()
