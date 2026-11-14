"""Sharing one speech backend between server instances.

MCP clients may start the server more than once (Claude Desktop starts one copy for chat and one
for its Cowork/Code sessions). The first instance becomes the *primary*: it owns the model, the
speakers, the microphone and a private local endpoint. Every other instance is a *secondary* and
forwards its requests to the primary, so there is only one speech, one listener and one answer.

The endpoint is a named pipe (Windows) or Unix socket, authenticated with a random key kept in a
file in the user's own directory. Messages are JSON, never pickle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from multiprocessing import AuthenticationError
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path

from kokoro_mcp.speech import InvalidSpeechRequest, SpeechController

log = logging.getLogger(__name__)

FAMILY = "AF_PIPE" if sys.platform == "win32" else "AF_UNIX"
KEY_BYTES = 32
CONTROL_OPS = ("pause", "resume", "stop", "describe", "state_label")
CONNECT_TIMEOUT = 5.0  # seconds to reach and greet the primary
REQUEST_TIMEOUT = 30.0  # seconds to wait for the primary's answer to a request


class PrimaryUnavailable(RuntimeError):
    """The primary instance cannot be reached."""


def endpoint_address(ipc_dir: Path) -> str:
    """Pipe name / socket path for an IPC directory (one endpoint per directory)."""
    digest = hashlib.sha1(str(ipc_dir.resolve()).encode()).hexdigest()[:12]
    if sys.platform == "win32":
        return rf"\\.\pipe\kokoro-mcp-{digest}"
    return str(Path(tempfile.gettempdir()) / f"kokoro-mcp-{digest}.sock")


def load_authkey(ipc_dir: Path) -> bytes:
    """Read the shared key, creating it (owner-only) if it does not exist yet."""
    ipc_dir.mkdir(parents=True, exist_ok=True)
    path = ipc_dir / "ipc.key"
    deadline = time.monotonic() + 2.0
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            key = path.read_bytes()
            if len(key) == KEY_BYTES:
                return key
            if time.monotonic() > deadline:  # leftovers from a crash while writing: replace them
                path.unlink(missing_ok=True)
                deadline = time.monotonic() + 2.0
            else:
                time.sleep(0.05)  # another instance is still writing the key
            continue
        key = secrets.token_bytes(KEY_BYTES)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
        return key


def open_listener(address: str, authkey: bytes) -> Listener | None:
    """Try to become the primary by taking the endpoint. Returns None if another instance holds it."""
    for _ in range(2):
        try:
            return Listener(address, family=FAMILY, authkey=authkey)
        except OSError:
            if FAMILY != "AF_UNIX" or not _is_stale_socket(address, authkey):
                return None
            Path(address).unlink(missing_ok=True)  # left behind by a crashed primary
    return None


def _is_stale_socket(address: str, authkey: bytes) -> bool:
    try:
        Client(address, family=FAMILY, authkey=authkey).close()
        return False
    except (ConnectionRefusedError, FileNotFoundError):
        return True
    except Exception:
        return False


def _send(conn: Connection, payload: dict) -> None:
    conn.send_bytes(json.dumps(payload).encode())


def _recv(conn: Connection, timeout: float | None = None) -> dict:
    """Read one message; with a timeout, raise TimeoutError if the peer stays silent."""
    if timeout is not None and not conn.poll(timeout):
        raise TimeoutError("no answer from the primary instance")
    return json.loads(conn.recv_bytes())


def _within(timeout: float, fn):
    """Run fn() in a helper thread and give up after `timeout` seconds (raises TimeoutError)."""
    box: dict = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=run, name="kokoro-ipc-connect", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutError("the primary instance did not answer")
    if "error" in box:
        raise box["error"]
    return box["value"]


class PrimaryServer:
    """Serves the speech service of the primary instance to secondary instances."""

    def __init__(self, listener: Listener, address: str, authkey: bytes, speech: SpeechController, pid: int) -> None:
        self._listener = listener
        self._address = address
        self._authkey = authkey
        self._speech = speech
        self._pid = pid
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, name="kokoro-ipc-accept", daemon=True)
        self._connections: set[Connection] = set()
        self._connections_lock = threading.Lock()

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        """Stop accepting, drop all secondaries and release the endpoint so another instance can take over."""
        self._stop.set()
        # Wake a blocked accept() with a throw-away connection. If the accept thread already exited
        # nobody answers it, so it must not be waited for: closing the listener releases it.
        waker = threading.Thread(target=self._wake_accept, name="kokoro-ipc-wake", daemon=True)
        waker.start()
        self._thread.join(1.0)
        self._listener.close()
        waker.join(0.5)
        with self._connections_lock:
            connections, self._connections = list(self._connections), set()
        for conn in connections:  # secondaries notice, and one of them takes over on its next call
            try:
                conn.close()
            except OSError:
                pass

    def _wake_accept(self) -> None:
        try:
            Client(self._address, family=FAMILY, authkey=self._authkey).close()
        except Exception:
            pass

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn = self._listener.accept()
            except AuthenticationError:
                log.warning("Rejected a connection to the speech endpoint (wrong key)")
                continue
            except Exception:
                if self._stop.is_set():
                    return
                log.exception("Speech endpoint failed to accept a connection")
                time.sleep(0.1)
                continue
            if self._stop.is_set():
                conn.close()
                return
            threading.Thread(target=self._serve, args=(conn,), name="kokoro-ipc-client", daemon=True).start()

    def _serve(self, conn: Connection) -> None:
        with self._connections_lock:
            self._connections.add(conn)
        try:
            while not self._stop.is_set():
                try:
                    request = _recv(conn)
                    _send(conn, self._handle(request))
                except (EOFError, OSError):
                    return
        finally:
            with self._connections_lock:
                self._connections.discard(conn)
            try:
                conn.close()
            except OSError:
                pass

    def _handle(self, request: dict) -> dict:
        op, caller = request.get("op"), request.get("pid")
        try:
            if op == "hello":
                return {"ok": True, "result": {"primary_pid": self._pid}}
            if op == "start":
                log.info("Speech request 'start' received from process %s (secondary)", caller)
                result = self._speech.start(request["text"], request["voice"], float(request["speed"]))
            elif op in CONTROL_OPS:
                log.info("Speech request '%s' received from process %s (secondary)", op, caller)
                result = getattr(self._speech, op)()
            else:
                return {"ok": False, "error": f"unknown operation {op!r}"}
        except InvalidSpeechRequest as exc:
            return {"ok": False, "invalid": str(exc)}
        except Exception as exc:
            log.exception("Speech request '%s' failed", op)
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "result": result}


class RemoteSpeechService:
    """Same interface as SpeechService, but every call is forwarded to the primary instance."""

    def __init__(self, address: str, authkey: bytes, pid: int) -> None:
        self._address = address
        self._authkey = authkey
        self._pid = pid
        self._lock = threading.Lock()
        self._conn: Connection | None = None
        self.primary_pid: int | None = None

    def connect(self) -> None:
        """Connect to the primary (raises PrimaryUnavailable if there is none)."""
        with self._lock:
            self._ensure_connection()

    def _ensure_connection(self) -> Connection:
        if self._conn is not None:
            return self._conn
        try:
            conn = _within(CONNECT_TIMEOUT, lambda: Client(self._address, family=FAMILY, authkey=self._authkey))
        except (OSError, EOFError, AuthenticationError) as exc:  # TimeoutError is an OSError
            raise PrimaryUnavailable("the primary instance is not reachable") from exc
        try:
            _send(conn, {"op": "hello", "pid": self._pid})
            self.primary_pid = _recv(conn, CONNECT_TIMEOUT)["result"]["primary_pid"]
        except (OSError, EOFError, KeyError, ValueError) as exc:
            conn.close()
            raise PrimaryUnavailable("the primary instance did not answer") from exc
        self._conn = conn
        return conn

    def _request(self, op: str, **arguments):
        with self._lock:
            conn = self._ensure_connection()
            log.info(
                "Speech redirected from process %s (secondary) to process %s (primary): %s",
                self._pid,
                self.primary_pid,
                op,
            )
            try:
                _send(conn, {"op": op, "pid": self._pid, **arguments})
                reply = _recv(conn, REQUEST_TIMEOUT)
            except (OSError, EOFError, ValueError) as exc:
                self._drop_connection()
                raise PrimaryUnavailable("lost the connection to the primary instance") from exc
        if reply.get("ok"):
            return reply["result"]
        if "invalid" in reply:
            raise InvalidSpeechRequest(reply["invalid"])
        raise RuntimeError(reply.get("error", "speech request failed in the primary instance"))

    def _drop_connection(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except OSError:
                pass
            self._conn = None

    def start(self, text: str, voice: str, speed: float) -> int:
        return self._request("start", text=text, voice=voice, speed=speed)

    def pause(self) -> bool:
        return self._request("pause")

    def resume(self) -> bool:
        return self._request("resume")

    def stop(self) -> bool:
        return self._request("stop")

    def describe(self) -> str:
        return self._request("describe")

    def state_label(self) -> str:
        return self._request("state_label")

    def shutdown(self) -> None:
        with self._lock:
            self._drop_connection()
