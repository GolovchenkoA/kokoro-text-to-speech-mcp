from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from mcp import Client

from kokoro_mcp.config import Settings
from server import build_app
from tests.fakes import FakeKokoro, FakeSoundDevice, FakeVosk, wait_until


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Replace audio, Kokoro and Vosk with fakes (the modules are imported lazily by the server)."""
    vosk = FakeVosk()
    sd, kokoro = FakeSoundDevice(vosk.phrases), FakeKokoro()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setitem(sys.modules, "kokoro", kokoro)
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    monkeypatch.chdir(tmp_path)  # lets tests assert that nothing is written to disk
    return SimpleNamespace(sd=sd, kokoro=kokoro, vosk=vosk, tmp_path=tmp_path)


@pytest.fixture
def make_app(fakes):
    """Build a fresh server app from Settings overrides; speech is stopped after the test."""
    apps = []

    def _make(**settings):
        app = build_app(Settings(**settings))
        apps.append(app)
        return app

    yield _make
    for app in apps:
        app.speech.shutdown()


@pytest.fixture
def app(make_app):
    return make_app()


def _text(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


class ToolResult(SimpleNamespace):
    text: str
    is_error: bool


@pytest.fixture
def call_tool(app):
    """Call an MCP tool through a real in-process MCP client/server connection."""

    def _call(name: str, **arguments) -> ToolResult:
        async def run():
            async with Client(app.mcp) as client:
                result = await client.call_tool(name, arguments)
            return ToolResult(text=_text(result), is_error=bool(result.is_error))

        return asyncio.run(run())

    return _call


@pytest.fixture
def list_tools(app):
    def _list():
        async def run():
            async with Client(app.mcp) as client:
                return (await client.list_tools()).tools

        return asyncio.run(run())

    return _list


def long_text(lines: int = 40) -> str:
    """Text that produces `lines` audio chunks (~0.5 s each) with the fake Kokoro."""
    return "\n".join(f"Sentence number {i}." for i in range(lines))


def begin_speech(app, fakes, lines: int = 40):
    """Start a long speech on `app` and wait until audio is flowing. Returns the session."""
    app.speech.start(long_text(lines), "af_heart", 1.0)
    session = app.speech.current_session
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[-1].frames > 0)
    return session
