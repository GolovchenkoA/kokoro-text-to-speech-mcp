"""Catalogue of the Kokoro languages and voices exposed by the server."""

from __future__ import annotations

# First letter of a voice ID == Kokoro lang_code.
LANGUAGES = {
    "a": "American English",
    "b": "British English",
    "e": "Spanish",
    "f": "French",
    "h": "Hindi",
    "i": "Italian",
    "j": "Japanese",
    "p": "Brazilian Portuguese",
    "z": "Mandarin Chinese",
}

VOICES = {
    "a": ["af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky", "am_adam", "am_michael", "am_fenrir", "am_puck"],
    "b": ["bf_emma", "bf_isabella", "bm_george", "bm_fable"],
    "e": ["ef_dora", "em_alex"],
    "f": ["ff_siwis"],
    "h": ["hf_alpha", "hf_beta", "hm_omega"],
    "i": ["if_sara", "im_nicola"],
    "j": ["jf_alpha", "jf_gongitsune", "jm_kumo"],
    "p": ["pf_dora", "pm_alex"],
    "z": ["zf_xiaobei", "zf_xiaoni", "zm_yunjian"],
}


def language_code(voice: str) -> str | None:
    """Kokoro language code for a voice ID, or None if the voice is not supported."""
    code = voice[:1].lower()
    return code if code in LANGUAGES else None


def voices_by_language() -> dict[str, list[str]]:
    return {LANGUAGES[code]: voices for code, voices in VOICES.items()}
