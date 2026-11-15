"""Decides whether this process is the primary instance or a secondary one, and delegates to it."""

from __future__ import annotations

import logging
import os
import threading
import time

from tts_mcp.config import Settings
from tts_mcp.ipc import (
    PrimaryUnavailable,
    RemoteSpeechService,
    endpoint_address,
    load_authkey,
    open_listener,
)
from tts_mcp.runtime import PrimaryRuntime
from tts_mcp.speech import SpeechController

log = logging.getLogger(__name__)

ELECTION_ATTEMPTS = 3


class InstanceManager:
    """A `SpeechController` that either does the work itself (primary / standalone) or forwards it to
    the primary instance (secondary). If the primary goes away, a secondary takes over on its next call."""

    def __init__(self, settings: Settings, pid: int | None = None) -> None:
        self._settings = settings
        self._pid = pid or os.getpid()
        self._lock = threading.RLock()
        self._runtime: PrimaryRuntime | None = None
        self._remote: RemoteSpeechService | None = None

    # -- role -------------------------------------------------------------------------------------
    @property
    def runtime(self) -> PrimaryRuntime | None:
        """The working runtime, or None while this instance is a secondary."""
        return self._runtime

    @property
    def role(self) -> str | None:
        if self._runtime is not None:
            return "primary"
        return "secondary" if self._remote is not None else None

    def activate(self) -> None:
        """Take part in the election: become the primary or connect to it as a secondary."""
        with self._lock:
            self._elect()

    def shutdown(self) -> None:
        with self._lock:
            runtime, remote = self._runtime, self._remote
            self._runtime = self._remote = None
        if runtime is not None:
            runtime.stop()
        if remote is not None:
            remote.shutdown()

    def _elect(self) -> None:
        if not self._settings.shared_instance:
            log.info("Instance process %s runs standalone (shared instance disabled)", self._pid)
            self._become_primary(None)
            return
        ipc_dir = self._settings.resolved_ipc_dir
        authkey = load_authkey(ipc_dir)
        address = endpoint_address(ipc_dir)
        for _ in range(ELECTION_ATTEMPTS):
            listener = open_listener(address, authkey)
            if listener is not None:
                self._become_primary((listener, address, authkey))
                return
            remote = RemoteSpeechService(address, authkey, self._pid)
            try:
                remote.connect()
            except PrimaryUnavailable:
                time.sleep(0.1)  # the primary just went away: try to take its place
                continue
            self._remote = remote
            log.info(
                "Instance process %s is a secondary: speech is redirected to process %s (primary)",
                self._pid,
                remote.primary_pid,
            )
            return
        log.warning("Could not join or become the primary instance; running standalone")
        self._become_primary(None)

    def _become_primary(self, endpoint) -> None:
        self._remote = None
        runtime = PrimaryRuntime(self._settings, self._pid, endpoint)
        runtime.start()
        self._runtime = runtime
        if endpoint is not None:
            log.info("Instance process %s is the primary", self._pid)

    def _reelect(self, failed: SpeechController) -> None:
        with self._lock:
            if self._backend() is not failed:
                return  # another thread already re-elected
            log.warning("Primary instance unavailable, process %s is taking over or reconnecting", self._pid)
            if self._remote is not None:
                self._remote.shutdown()
                self._remote = None
            self._elect()

    # -- SpeechController ----------------------------------------------------------------------
    def _backend(self) -> SpeechController:
        with self._lock:
            if self._runtime is not None:
                return self._runtime.speech
            if self._remote is not None:
                return self._remote
        raise PrimaryUnavailable("the server instance is not started")

    def _delegate(self, name: str, *args):
        for _ in range(2):
            backend = self._backend()
            try:
                return getattr(backend, name)(*args)
            except PrimaryUnavailable:
                self._reelect(backend)
        raise PrimaryUnavailable("the speech backend is unavailable")

    def start(self, text: str, voice: str, speed: float) -> int:
        return self._delegate("start", text, voice, speed)

    def pause(self) -> bool:
        return self._delegate("pause")

    def resume(self) -> bool:
        return self._delegate("resume")

    def stop(self) -> bool:
        return self._delegate("stop")

    def describe(self) -> str:
        return self._delegate("describe")

    def state_label(self) -> str:
        return self._delegate("state_label")
