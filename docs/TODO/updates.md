# TODO: Prepare the MCP server for Agensi.io (MCP server + skill)

## Question

> What do I need to make the following updates: We run Agensi.io, a marketplace for AI agent skills, and we like the MCP server you built. Paired with a skill that tells the agent when and how to use it, it becomes something people can install straight into Claude Code, Cursor, Copilot and 20+ other agents

## Answer (summary)

The pairing means the MCP server plus a `SKILL.md` that teaches the agent when and how to use it (approach "a" from the earlier skill analysis).
The Agensi message and its terms are **not verified**: check their terms and contact them through their official site.
The current `skill-draft/kokoro-tts/` is the self-contained variant (a CLI script that duplicates the TTS). For this deal it should become a skill that uses the server instead.

Done when every box below is checked.

## Steps

### 1. Rename the project (do this first)

Give the project a unique name that does not mention Kokoro or any other tool or engine (no Kokoro, Vosk, Claude, MCP-vendor names and so on), so it stays valid if the engine changes and is not confused with an existing project. Descriptive text (README, docs) may still say which engine is used.

- [ ] Choose a short, unique, tool-neutral name
  - Possible solution (not final): **Larkspeak**. On 2026-11-15 the exact name was free on PyPI and npm and a GitHub search for repositories named `larkspeak` returned 0. Not checked: Agensi.io, trademarks, domains, social handles, general web search.
- [ ] Check that it is free: GitHub, PyPI, npm, Agensi.io and a web search
- [ ] Rename the GitHub repository (GitHub redirects the old URL)
- [ ] Rename the local project folder and update the PyCharm project and any run configurations
- [ ] Rename the Python package folder `kokoro_mcp/` and fix all imports
- [ ] Rename the MCP server (`MCPServer("kokoro-tts")` and the `kokoro-tts` key in the Claude config examples)
- [ ] Rename the environment variables `KOKORO_*` to the new prefix (`KOKORO_VOICE_CONTROL_ENABLED`, `KOKORO_DEFAULT_VOICE`, `KOKORO_VAD*`, `KOKORO_SHARED_INSTANCE`, `KOKORO_IPC_DIR`, `KOKORO_VOSK_MODEL`, `KOKORO_MIC_DEVICE`, `KOKORO_DEVICE`) and decide whether to keep the old names as aliases
- [ ] Rename the key directory `~/.kokoro_mcp`, the log logger names and the pipe/socket names
- [ ] Update `README.md`, `docs/`, `.python-version` notes, tests and `skill-draft/`
- [ ] Update the installed Claude Desktop / Claude Code config to the new name and path, then restart
- [ ] Run the tests (`python -m pytest`) and start the server once to confirm the rename

### 2. Skill for the MCP server

Replace the self-contained `skill-draft/kokoro-tts/` with a skill that tells the agent when and how to use the server. No scripts and no setup beyond the install step.

- [ ] Write `SKILL.md` with `name` and a trigger-friendly `description` ("read aloud", "narrate", "speak this", "voiceover", "pause/stop speech")
- [ ] Explain when to call `start_speech` and to pass the text verbatim
- [ ] Explain how to pick a voice that matches the text language (and that there is no Polish voice)
- [ ] Explain pause, resume, stop and status, and the voice commands
- [ ] Describe the `speak-last-reply` prompt and a fallback for agents without MCP prompts: call `start_speech` with the previous answer unchanged
- [ ] Remove `scripts/` and the duplicated TTS code from the skill folder
- [ ] Test the skill in Claude Code and one other agent (Cursor or Copilot)

### 3. Make the server easy to install

Today a buyer must clone the repo, create a venv on Python 3.12–3.14, run `pip install` with special flags, install `espeak-ng` and edit a config by hand.

- [ ] Add `pyproject.toml` with a console command (for example `<new-name>`)
- [ ] Fix the supported Python range (the speech engine blocks 3.13+)
- [ ] Publish to PyPI so one line works: `uvx <new-name>`
- [ ] Document config snippets for Claude Code (`claude mcp add`), Cursor, VS Code / Copilot and Claude Desktop
- [ ] Consider a `.mcpb` / plugin package (see `docs/TODO/Local MCP updates.md`)
- [ ] Document the `espeak-ng` system dependency per OS

### 4. License and notices

The repository has no license file.

- [ ] Choose a license and add `LICENSE`
- [ ] Add a third-party notices file (`espeak-ng` and `phonemizer-fork` are GPL and installed by pip, not bundled)
- [ ] Re-check the licenses of the speech model, voices and the recognition model
- [ ] Check the Agensi terms for licensing and revenue share

### 5. Security and privacy

- [ ] Decide the voice-control default for the released package: it is now **on** (opens the microphone, downloads a ~40 MB model at first start); a marketplace scan and buyers may flag it
- [ ] Add a privacy and permissions section to the README (microphone, runtime model downloads, key file, local pipe/socket)
- [ ] Document the runtime downloads (speech model from Hugging Face, recognition model)
- [ ] Confirm there is no shell execution, hardcoded paths or secrets

### 6. Testing on other systems

Only tested on Windows, and the tests use fakes for audio and models.

- [ ] Test on macOS (microphone permission, `espeak-ng` via Homebrew)
- [ ] Test on Linux (PortAudio, `espeak-ng`)
- [ ] Test with a real microphone and real models end to end
- [ ] Add CI that runs `pytest` on Windows, macOS and Linux

### 7. Release

- [ ] Merge `feature/advanced-speech-control` into `main` and push
- [ ] Tag a version and add a changelog
- [ ] Publish the package, then the skill listing on Agensi.io
- [ ] Verify a clean install from scratch on a second machine
