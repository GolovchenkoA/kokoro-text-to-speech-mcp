from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest
from mcp import Client

import server
from tests.fakes import FakeKokoro, FakeSoundDevice, FakeVosk


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    """Replace audio, Kokoro and Vosk with fakes and reset the server's global state."""
    vosk = FakeVosk()
    sd, kokoro = FakeSoundDevice(vosk.phrases), FakeKokoro()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setitem(sys.modules, "kokoro", kokoro)
    monkeypatch.setitem(sys.modules, "vosk", vosk)
    monkeypatch.delenv("KOKORO_WAKEWORD", raising=False)
    monkeypatch.delenv("KOKORO_VOSK_MODEL", raising=False)
    monkeypatch.delenv("KOKORO_MIC_DEVICE", raising=False)
    monkeypatch.delenv("KOKORO_VAD", raising=False)
    monkeypatch.delenv("KOKORO_VAD_THRESHOLD", raising=False)
    monkeypatch.chdir(tmp_path)  # lets tests assert that nothing is written to disk
    server._session = None
    server._pipelines.clear()
    yield SimpleNamespace(sd=sd, kokoro=kokoro, vosk=vosk, tmp_path=tmp_path)
    if server._session is not None:
        server._session.stop()
        server._session.join(2.0)
    server._session = None
    server._pipelines.clear()


class ToolResult(SimpleNamespace):
    text: str
    is_error: bool


@pytest.fixture
def call_tool(fakes):
    """Call an MCP tool through a real in-process MCP client/server connection."""

    def _call(name: str, **arguments) -> ToolResult:
        async def run():
            async with Client(server.mcp) as client:
                result = await client.call_tool(name, arguments)
            text = "".join(getattr(block, "text", "") for block in result.content)
            return ToolResult(text=text, is_error=bool(result.is_error))

        return asyncio.run(run())

    return _call


@pytest.fixture
def list_tools(fakes):
    def _list():
        async def run():
            async with Client(server.mcp) as client:
                return (await client.list_tools()).tools

        return asyncio.run(run())

    return _list


def long_text(lines: int = 40) -> str:
    """Text that produces `lines` audio chunks (~0.5 s each) with the fake Kokoro."""
    return "\n".join(f"Sentence number {i}." for i in range(lines))
