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

### 2.1 Synthesizer interface

- [ ] Define a synthesizer interface: `synthesize(text, voice, speed)` yields mono float32 chunks, plus `sample_rate` as a property of the synthesizer
- [ ] Turn the current `SpeechSynthesizer` into the Kokoro implementation of that interface
- [ ] Remove the global `SAMPLE_RATE`: playback (`audio.py`), slicing (`speech.py`) and the announcer take the rate from the active synthesizer
- [ ] Remove the rule "first letter of the voice ID is the language" from `voices.py`; the language comes from the config
- [ ] Remove the hardcoded `af_heart` (default voice and announcer voice); take them from the config
- [ ] Define how a model that does not stream is handled (split text into sentences so pause and stop stay responsive)
- [ ] Add a registry that creates a synthesizer by model name and loads each model lazily
- [ ] Update the test fakes to implement the interface

### 2.2 External configuration file

An external file lists the models and what they support.

- [ ] Decide the format (JSON, TOML or YAML) and the default location, plus an environment variable to point to another file
- [ ] Define the schema:
  - [ ] list of text-to-speech models (id, implementation, device and options)
  - [ ] supported languages per model
  - [ ] voices per model and language
  - [ ] the default model
  - [ ] the default voice per model + language
- [ ] Ship a default file with the models that are supported
- [ ] Load and validate the file at start; fail with a clear message on an unknown default model, voice or language
- [ ] Keep `Settings` overrides (default model, default voice) working on top of the file
- [ ] Document the file format in the README

### 2.3 New models

- [ ] Pick the models to add (more languages or voices, license allows redistribution, runs offline)
- [ ] Check each model's license, sample rate, streaming support and system dependencies
- [ ] Implement one synthesizer class per model
- [ ] Add the models to the default config file with their languages and voices
- [ ] Add the dependencies as optional extras so a user installs only the models they need
- [ ] Document the install steps per model (including system packages such as `espeak-ng`)

### 2.4 Choosing and switching models

- [ ] Add an optional `model` parameter to `start_speech`
- [ ] Choose the model automatically when none is given: use the model that supports the language of the requested voice, otherwise the default model
- [ ] Switch the model when the requested voice or language is not supported by the current one
- [ ] Return a clear error when no configured model supports the request
- [ ] Release or reuse loaded models (decide how many stay in memory)
- [ ] Make sure the primary/secondary instances share the model choice and load models only in the primary
- [ ] Update the status announcer to use the default voice of the active model

### 2.5 Tool that lists models, languages and voices

- [ ] Add a tool that lists the supported models, and for each model its languages and voices (data comes from the config file)
- [ ] Mark the default model and the default voice per model + language
- [ ] Replace or extend the existing `list_voices` tool (decide which)
- [ ] Update the tool and prompt descriptions so the agent picks a voice that matches the text language
- [ ] Update the skill (`docs/TODO/updates.md`, step 2) once the tool exists

### 2.6 Tests and docs

- [ ] Tests for the interface with two fake models
- [ ] Tests for the config file: valid file, missing file, unknown default, unsupported language
- [ ] Tests for model selection and switching
- [ ] Tests for the listing tool
- [ ] Update the README (models, languages, config file, install per model)
- [ ] Full test run
