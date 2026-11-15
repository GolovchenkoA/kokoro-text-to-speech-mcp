"""Choosing the compute device. A GPU is used when there is one; otherwise everything runs on the CPU."""

from __future__ import annotations

import functools
import logging

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def available_devices() -> frozenset[str]:
    """The devices this machine offers. The CPU is always there; the rest need PyTorch."""
    devices = {"cpu"}
    try:
        import torch  # heavy import, and optional for engines that do not use it
    except ImportError:
        return frozenset(devices)
    try:
        if torch.cuda.is_available():
            devices.add("cuda")
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            devices.add("mps")
    except Exception:  # a broken driver must not stop the server: the CPU still works
        log.exception("Could not query the GPU, using the CPU")
    return frozenset(devices)


def resolve_device(requested: str | None) -> str:
    """Turn a requested device ("auto", "cpu", "cuda", "mps" or None) into one that exists.

    "auto" prefers CUDA, then MPS, then the CPU. A named device that is not available falls back to
    the CPU with a warning instead of failing.
    """
    wanted = (requested or "auto").strip().lower()
    devices = available_devices()
    if wanted == "auto":
        return "cuda" if "cuda" in devices else "mps" if "mps" in devices else "cpu"
    if wanted in devices:
        return wanted
    log.warning("Device '%s' is not available, falling back to the CPU", wanted)
    return "cpu"
