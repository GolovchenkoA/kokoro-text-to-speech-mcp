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
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)  # lets tests assert that nothing is written to disk
    return SimpleNamespace(sd=sd, kokoro=kokoro, vosk=vosk, tmp_path=tmp_path, workdir=workdir)


@pytest.fixture
def make_app(fakes):
    """Build and activate a server app from Settings overrides; it is shut down after the test.

    Apps made in one test share the same IPC directory, so the first becomes the primary instance
    and later ones become secondaries. Pass `pid=` to give an app a fake process id.
    """
    apps = []

    def _make(pid: int | None = None, activate: bool = True, **settings):
        settings.setdefault("ipc_dir", fakes.tmp_path / "ipc")
        app = build_app(Settings(**settings), pid)
        apps.append(app)
        if activate:
            app.manager.activate()
        return app

    yield _make
    for app in apps:
        app.manager.shutdown()


@pytest.fixture
def app(make_app):
    return make_app()


def _text(result) -> str:
    return "".join(getattr(block, "text", "") for block in result.content)


class ToolResult(SimpleNamespace):
    text: str
    is_error: bool


def call_tool_on(app, name: str, **arguments) -> ToolResult:
    """Call an MCP tool through a real in-process MCP client/server connection."""

    async def run():
        async with Client(app.mcp) as client:
            result = await client.call_tool(name, arguments)
        return ToolResult(text=_text(result), is_error=bool(result.is_error))

    return asyncio.run(run())


@pytest.fixture
def call_tool(app):
    """Call tools on the default app."""
    return lambda name, **arguments: call_tool_on(app, name, **arguments)


@pytest.fixture
def list_tools(app):
    def _list():
        async def run():
            async with Client(app.mcp) as client:
                return (await client.list_tools()).tools

        return asyncio.run(run())

    return _list


@pytest.fixture
def list_prompts(app):
    def _list():
        async def run():
            async with Client(app.mcp) as client:
                return (await client.list_prompts()).prompts

        return asyncio.run(run())

    return _list


@pytest.fixture
def get_prompt_text(app):
    """Text of the (single) message a prompt returns."""

    def _get(name: str, **arguments: str) -> str:
        async def run():
            async with Client(app.mcp) as client:
                return await client.get_prompt(name, arguments or None)

        messages = asyncio.run(run()).messages
        assert len(messages) == 1 and messages[0].role == "user"
        return messages[0].content.text

    return _get


def long_text(lines: int = 40) -> str:
    """Text that produces `lines` audio chunks (~0.5 s each) with the fake Kokoro."""
    return "\n".join(f"Sentence number {i}." for i in range(lines))


def begin_speech(app, fakes, lines: int = 40):
    """Start a long speech on the primary `app` and wait until audio is flowing. Returns the session."""
    speech = app.manager.runtime.speech
    speech.start(long_text(lines), "af_heart", 1.0)
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[-1].frames > 0)
    return speech.current_session
