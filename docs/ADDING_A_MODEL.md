# Adding or switching a speech model

Models are defined in `models.json` (or the file named by `TTS_MODELS_FILE`). The server code names no model.

## Switch the default model

Set `"default_model"` to another key under `"models"`. Restart the server. Nothing else changes.

## Add a model that uses an existing engine

Copy a model entry, give it a new key and change `options` (for example `"repo"`), `languages` and `voices`. The engine class stays the same:

```json
"qwen3-large": {
  "name": "Qwen3-TTS 1.7B (preset voices)",
  "engine": "tts_mcp.engines.qwen3:Qwen3Engine",
  "sample_rate": 24000,
  "options": { "repo": "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice" },
  "voices": ["Ryan", "Aiden"],
  "languages": { "en": { "name": "English", "engine_code": "English", "default_voice": "Ryan" } }
}
```

## Fields of a model entry

| Field | Required | Meaning |
|---|---|---|
| `engine` | yes | Import path `package.module:ClassName` of the engine class |
| `sample_rate` | yes | Hz of the audio the engine yields; the speakers are opened at this rate |
| `name` | no | Display name |
| `device` | no | `auto` (default), `cpu`, `cuda` or `mps`. A device that is missing falls back to the CPU |
| `options` | no | Free-form object passed to the engine (for example `repo`) |
| `voices` | no | Voices shared by every language of the model |
| `languages` | yes | Languages of the model, in order; the first is the model's default language |

Each language: `name`, `engine_code` (what the engine calls the language; defaults to the key), `default_voice` (defaults to the first voice) and optional `voices` (defaults to the model's `voices`). A language key such as `en-us` also answers to `en`.

A request with no model uses the default model, or the first model that has the requested voice and language.

## Add a new model family (one new class)

1. Write an engine class in `tts_mcp/engines/` (or any importable module). It is built as `Engine(spec, device)`, loads its model on the first call, and implements `synthesize(text, voice, language, speed)`, yielding mono float32 chunks at `spec.sample_rate`. See `tts_mcp/engines/base.py`.
2. Use `tts_mcp.devices.resolve_device` to choose the device: it returns the GPU when there is one and the CPU otherwise.
3. If the model returns a whole waveform, cut the text with `tts_mcp.engines.text.split_text` so playback starts early and pause stays responsive.
4. Add the entry to `models.json` with `"engine": "your.module:YourEngine"`.

No other code changes: the catalogue, the synthesizer, the tools and the voice commands work for any engine.

## Rules for every model

See [APP_REQUIREMENTS.md](APP_REQUIREMENTS.md): the license must allow commercial use, audio stays in memory (no files), and the model must run on a CPU.
