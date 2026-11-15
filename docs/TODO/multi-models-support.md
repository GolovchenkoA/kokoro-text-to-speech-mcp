# TODO: Multiple text-to-speech models

Two goals, in this order:

1. Get rid of mentioning Kokoro where it is not required.
2. Refactor the app so it can use different text-to-speech models.

Done when every box below is checked.

Related: step 1 of `docs/TODO/updates.md` (rename the project) overlaps with goal 1. Do them together, or do the rename first and skip the duplicated boxes here.

## Goal 1. Remove Kokoro mentions where not required

Descriptive text (README, docs) may still say which engine is used. Code and public names must not depend on it.

- [x] Rename the Python package `kokoro_mcp/` and fix all imports (now `tts_mcp/`)
- [x] Rename the MCP server name (`MCPServer("kokoro-tts")`) and the key in the Claude config examples (now `tts`)
- [x] Rename the `KOKORO_*` environment variables to a neutral prefix, decide whether to keep the old names as aliases (now `TTS_*`, no aliases)
- [x] Rename the key directory `~/.kokoro_mcp`, thread names, logger names and the pipe/socket names
- [x] Replace "Kokoro voice ID" and similar wording in tool and prompt descriptions (`mcp_tools.py`)
- [x] Update README and `docs/` so Kokoro appears only where it names the engine in use
- [x] Update tests (`tests/fakes.py`, `tests/conftest.py`, names and env vars)
- [ ] Run the tests (`python -m pytest`) and start the server once to confirm (tests pass, 107; the server has not been started yet)

## Goal 2. Support different text-to-speech models

Scope decision: only **Qwen3-TTS** is added as a second model (plain text-to-speech with the preset voices, no voice cloning, no voice design). Chatterbox, MOSS-TTS-Nano and Supertonic from `MODELS_LEGAL_REPORT.md` are not added.

Design: Strategy (`SpeechEngine`), Factory by import path (`create_engine`), and a catalogue read from `models.json`. Replacing the default model or adding a model with an existing engine is a change to the file only. See `docs/ADDING_A_MODEL.md`.

### 2.1 Engine interface

- [x] Define an engine interface: `synthesize(text, voice, language, speed)` yields mono float32 chunks (`tts_mcp/engines/base.py`); the sample rate is a property of the model in the file, read through `SpeechSynthesizer.sample_rate(model)`
- [x] Turn the current `SpeechSynthesizer` into the Kokoro implementation of that interface (`tts_mcp/engines/kokoro.py`; `SpeechSynthesizer` is now a router that knows no model)
- [x] Remove the global `SAMPLE_RATE`: playback (`audio.py`), slicing (`speech.py`) and the announcer take the rate from the selected model
- [x] Remove the rule "first letter of the voice ID is the language" (`voices.py` is deleted); the language comes from the file
- [x] Remove the hardcoded `af_heart` (default voice and announcer voice); the defaults come from the file, the announcer uses the first model that speaks English
- [x] Define how a model that does not stream is handled (`split_text` cuts the text into short pieces so pause and stop stay responsive)
- [x] Add a factory that creates an engine by the import path in the file and loads each model lazily
- [x] Update the test fakes (fake `kokoro`, `qwen_tts` and `torch` modules, and an engine that exists only in a test's models file)

### 2.2 External configuration file

- [x] Format: JSON, `models.json` next to `server.py`, `TTS_MODELS_FILE` points to another file
- [x] Schema:
  - [x] list of text-to-speech models (engine class, sample rate, device, options)
  - [x] supported languages per model
  - [x] voices per model and language (a model can list voices once for all its languages)
  - [x] the default model
  - [x] the default voice per model + language
- [x] Ship a default file with the supported models
- [x] Load and validate the file at start; the server stops with a message that names the file and the problem
- [x] Settings overrides: decided against a default-model or default-voice override in the environment, so the file is the only place that decides (`TTS_DEVICE` stays as an override)
- [x] Document the file format (README, `docs/ADDING_A_MODEL.md`)

### 2.3 New model: Qwen3-TTS only

- [x] Pick the model: Qwen3-TTS 0.6B CustomVoice (preset voices, Apache 2.0 per `MODELS_LEGAL_REPORT.md`)
- [x] Implement the engine class (`tts_mcp/engines/qwen3.py`): GPU when available, CPU otherwise, also when the GPU fails to load the model; speed is ignored (the model has no speed control)
- [x] Add the model to `models.json` with its languages and voices
- [x] Add the dependency as an optional file (`requirements-qwen3.txt`)
- [x] Document the install steps (README)
- [ ] Run it with the real model: this was written from the Qwen3-TTS README and tested only with fakes. Check on a real machine:
  - [ ] `qwen-tts` installs next to the Kokoro packages (dependency conflicts, Python version)
  - [ ] the real sample rate (24 kHz is assumed; the engine resamples if it differs)
  - [ ] the language names (`English`, `German`, ... were assumed from `Chinese` and `English` in the README; `model.get_supported_languages()` lists the real ones)
  - [ ] speed and quality on a CPU, and that the CPU fallback works without a GPU
  - [ ] the license of the weights file on Hugging Face (the report relies on the model metadata)

### 2.4 Choosing and switching models

- [x] Add optional `model` and `language` parameters to `start_speech`, and make `voice` optional
- [x] Choose the model automatically when none is given: the default model first, then the first model that has the requested voice and language
- [x] Switch the model when the requested voice or language is not supported by the default one
- [x] Return a clear error when no configured model supports the request
- [x] Loaded models stay loaded once used (decided: a model is loaded on first use and kept)
- [x] Primary/secondary instances: the primary resolves the request and loads models; a secondary only forwards it
- [x] Update the status announcer (uses the first model that speaks English and its default voice)

### 2.5 Tool that lists models, languages and voices

- [x] `list_models` lists the models, and for each model its languages and voices (data comes from the file)
- [x] The default model and the default voice per model + language are included
- [x] `list_models` replaces `list_voices`
- [x] Update the tool descriptions and the skill so the agent picks a voice and language that match the text
- [x] Update the skill (`plugins/larkspeak/skills/larkspeak/SKILL.md`)

### 2.6 Tests and docs

- [x] Tests for the engines with two fake models and a model that exists only in a test file
- [x] Tests for the file: valid file, missing file, invalid JSON, unknown default, bad engine path, unsupported language
- [x] Tests for model selection and switching, also through a secondary instance
- [x] Tests for the listing tool
- [x] Tests for the CPU fallback (no GPU, GPU present, GPU fails to load, GPU requested but missing)
- [x] Update the README (models, languages, file, install per model)
- [x] Full test run (171 tests pass)
