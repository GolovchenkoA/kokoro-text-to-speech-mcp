from __future__ import annotations

import asyncio
import json
import sys
from types import SimpleNamespace

import pytest
from mcp import Client

from tts_mcp import devices
from tts_mcp.config import Settings
from server import build_app
from tests.fakes import all_models_data, FakeEngine, FakeQwen, FakeSoundDevice, FakeTorch, FakeVosk, wait_until


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Replace audio, the speech engine and Vosk with fakes (the modules are imported lazily by the server)."""
    vosk = FakeVosk()
    sd, engine, qwen = FakeSoundDevice(vosk.phrases), FakeEngine(), FakeQwen()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setitem(sys.modules, "kokoro", engine)
    monkeypatch.setitem(sys.modules, "qwen_tts", qwen)
    monkeypatch.setitem(sys.modules, "torch", FakeTorch())
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    gpus = {"available": frozenset({"cpu"})}  # tests change this to pretend a GPU exists
    monkeypatch.setattr(devices, "available_devices", lambda: gpus["available"])
    models_file = tmp_path / "all-models.json"
    models_file.write_text(json.dumps(all_models_data()), encoding="utf-8")
    workdir = tmp_path / "work"
    workdir.mkdir()
    monkeypatch.chdir(workdir)  # lets tests assert that nothing is written to disk
    return SimpleNamespace(
        sd=sd, engine=engine, qwen=qwen, vosk=vosk, gpus=gpus, tmp_path=tmp_path, workdir=workdir, models_file=models_file
    )


@pytest.fixture
def make_app(fakes):
    """Build and activate a server app from Settings overrides; it is shut down after the test.

    Apps made in one test share the same IPC directory, so the first becomes the primary instance
    and later ones become secondaries. Pass `pid=` to give an app a fake process id. Voice control
    (on by default in Settings) is off here unless a test passes `is_voice_control_enabled=True`.
    The language check is off too, unless a test passes a fake `detector=`.
    """
    apps = []

    def _make(pid: int | None = None, activate: bool = True, detector=None, **settings):
        settings.setdefault("ipc_dir", fakes.tmp_path / "ipc")
        settings.setdefault("models_file", fakes.models_file)  # every model enabled, as the tests need them
        settings.setdefault("is_voice_control_enabled", False)
        settings.setdefault("language_check", detector is not None)  # off unless a test brings a detector
        app = build_app(Settings(**settings), pid, detector)
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
    """Text that produces `lines` audio chunks (~0.5 s each) with the fake engine."""
    return "\n".join(f"Sentence number {i}." for i in range(lines))


def begin_speech(app, fakes, lines: int = 40):
    """Start a long speech on the primary `app` and wait until audio is flowing. Returns the session."""
    speech = app.manager.runtime.speech
    speech.start(long_text(lines), "af_heart", 1.0)
    assert wait_until(lambda: fakes.sd.streams and fakes.sd.streams[-1].frames > 0)
    return speech.current_session
