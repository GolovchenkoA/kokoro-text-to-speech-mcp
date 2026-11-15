"""Errors shared by the speech components."""

from __future__ import annotations


class EngineUnavailable(RuntimeError):
    """A model cannot run on this machine, for example because its package is not installed."""


class InvalidSpeechRequest(ValueError):
    """The text, voice, model, language or speed of a speech request is not acceptable."""
