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
  - Possible solution (not final): **Larkspeak**. The plugin, the skill, the buttons mod and the marketplace already use it (`plugins/larkspeak/` and `plugins/larkspeak-buttons/`), so they must be renamed too if another name is chosen. On 2026-11-15 the exact name was free on PyPI and npm and a GitHub search for repositories named `larkspeak` returned 0. Not checked: Agensi.io, trademarks, domains, social handles, general web search.
- [ ] Check that it is free: GitHub, PyPI, npm, Agensi.io and a web search
- [ ] Rename the GitHub repository (GitHub redirects the old URL)
- [ ] Rename the local project folder and update the PyCharm project and any run configurations
- [x] Rename the Python package folder `kokoro_mcp/` and fix all imports (done: now `tts_mcp/`; the code uses a neutral name on purpose, so a later project rename does not touch it)
- [x] Rename the MCP server (`MCPServer("kokoro-tts")` and the `kokoro-tts` key in the Claude config examples) (done: now `tts`)
- [x] Rename the environment variables `KOKORO_*` to the new prefix (`KOKORO_VOICE_CONTROL_ENABLED`, `KOKORO_DEFAULT_VOICE`, `KOKORO_VAD*`, `KOKORO_SHARED_INSTANCE`, `KOKORO_IPC_DIR`, `KOKORO_VOSK_MODEL`, `KOKORO_MIC_DEVICE`, `KOKORO_DEVICE`) and decide whether to keep the old names as aliases (done: now `TTS_*`, no aliases kept)
- [x] Rename the key directory `~/.kokoro_mcp`, the log logger names and the pipe/socket names (done: `~/.tts_mcp`, `tts-mcp-*`, `tts-*` thread names)
- [x] Update `README.md`, `docs/`, tests (done; the name Larkspeak is used in the README, the plugins and the plugin docs, not in the code). Still open: `.python-version` notes and `skill-draft/`
- [ ] Update the installed Claude Desktop / Claude Code config to the new name and path, then restart (the server key is now `tts`, the buttons and the skill look for it)
- [ ] Run the tests (`python -m pytest`) and start the server once to confirm the rename (tests pass, 107; the server has not been started yet)

### 2. Skill for the MCP server

Replace the self-contained `skill-draft/kokoro-tts/` with a skill that tells the agent when and how to use the server. No scripts and no setup beyond the install step.

- [x] Write `SKILL.md` with `name` and a trigger-friendly `description` ("read aloud", "narrate", "speak this", "voiceover", "pause/stop speech") (done: `plugins/larkspeak/skills/larkspeak/SKILL.md`)
- [x] Explain when to call `start_speech` and to pass the text verbatim
- [x] Explain how to pick a voice that matches the text language (and that there is no Polish voice) (done in general terms; it does not name Polish, and the voice list will change with multi-model support)
- [x] Explain pause, resume, stop and status, and the voice commands
- [x] Describe the `speak-last-reply` prompt and a fallback for agents without MCP prompts: call `start_speech` with the previous answer unchanged
- [ ] Remove `scripts/` and the duplicated TTS code from the skill folder (the new skill has no scripts, but the old `skill-draft/kokoro-tts/` still exists and should be deleted)
- [ ] Test the skill in Claude Code and one other agent (Cursor or Copilot)

### 3. Make the server easy to install

Today a buyer must clone the repo, create a venv on Python 3.12–3.14, run `pip install` with special flags, install `espeak-ng` and edit a config by hand.

- [ ] Add `pyproject.toml` with a console command (for example `<new-name>`)
- [ ] Fix the supported Python range (the speech engine blocks 3.13+)
- [ ] Publish to PyPI so one line works: `uvx <new-name>`
- [ ] Document config snippets for Claude Code (`claude mcp add`), Cursor, VS Code / Copilot and Claude Desktop (done for Claude Code and Claude Desktop in `docs/PLUGIN_INSTALLATION.md` and the README; Cursor and VS Code / Copilot are missing)
- [x] Consider a `.mcpb` / plugin package (see `docs/TODO/Local MCP updates.md`) (plugin package and marketplace file created; not tested on a clean computer; the plugin has no `.mcp.json` until the PyPI release; `.mcpb` not done)
- [x] Add the Larkspeak buttons mod (read aloud, pause, continue, stop under each reply) as its own optional plugin `larkspeak-buttons`, separate from the skill plugin `larkspeak` (`plugins/larkspeak-buttons/hooks/`; tested as a dev mod, not as an installed plugin)
- [x] Write installation instructions for a new computer (`docs/PLUGIN_INSTALLATION.md`; the commands have not been run on a clean computer)
- [x] Document the `espeak-ng` system dependency per OS (README and `docs/PLUGIN_INSTALLATION.md`)

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
