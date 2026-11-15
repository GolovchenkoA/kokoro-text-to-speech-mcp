"""Errors shared by the speech components."""

from __future__ import annotations


class InvalidSpeechRequest(ValueError):
    """The text, voice, model, language or speed of a speech request is not acceptable."""
