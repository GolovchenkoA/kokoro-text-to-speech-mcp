# Larkspeak plugin: installation on a new computer

Larkspeak has three parts. The server is required. The two plugins are independent, so install only what you need:

| Part | What it is | Where it lives |
|---|---|---|
| Speech MCP server (required) | Python program that speaks text locally (speakers, optional voice commands) | repo root (`server.py`, `tts_mcp/`) |
| Plugin `larkspeak` | A skill that tells the agent when and how to speak | `plugins/larkspeak/` |
| Plugin `larkspeak-buttons` (optional) | Read aloud / pause / continue / stop buttons under each reply | `plugins/larkspeak-buttons/` |

Neither plugin starts the server yet. Install the server first (steps 1 to 3), then the plugins you want (step 4). The buttons work without the skill, and the skill works without the buttons.

> The plugin and marketplace files are on the branch `feature/advanced-speech-control`. Until it is merged into `master`, a marketplace added from GitHub will not see them. Merge first, or add the marketplace from a local clone (step 4, option B).

## 1. Prerequisites

| Needed | Windows | macOS | Linux |
|---|---|---|---|
| Claude Code or Claude Desktop | install from claude.ai | same | Claude Code |
| Git | git-scm.com | `brew install git` | `sudo apt install git` |
| Python 3.12 (3.14 also works, see README) | python.org or `py -3.12` | `brew install python@3.12` | `sudo apt install python3.12 python3.12-venv` |
| `espeak-ng` | `.msi` from https://github.com/espeak-ng/espeak-ng/releases | `brew install espeak-ng` | `sudo apt install espeak-ng` |
| PortAudio | bundled | bundled | `sudo apt install libportaudio2` |
| Working speakers, and a microphone for voice commands | | | |

## 2. Get the server and install its packages

Windows (PowerShell):

```powershell
git clone https://github.com/GolovchenkoA/kokoro-text-to-speech-mcp.git
cd kokoro-text-to-speech-mcp
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install srt
python -m pip install --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

macOS and Linux:

```bash
git clone https://github.com/GolovchenkoA/kokoro-text-to-speech-mcp.git
cd kokoro-text-to-speech-mcp
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install srt
python -m pip install --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

On Python 3.14, add `--ignore-requires-python` to the second `pip install`. The first start downloads the speech model (and about 40 MB for voice commands), so it needs internet once.

## 3. Register the server with Claude

Use absolute paths to the venv's Python and to `server.py`. The server name must be `tts`, because the buttons and the skill look for that name.

Claude Code, Windows:

```powershell
claude mcp add tts --scope user -- "C:\path\to\kokoro-text-to-speech-mcp\.venv\Scripts\python.exe" "C:\path\to\kokoro-text-to-speech-mcp\server.py"
```

Claude Code, macOS and Linux:

```bash
claude mcp add tts --scope user -- /absolute/path/to/kokoro-text-to-speech-mcp/.venv/bin/python /absolute/path/to/kokoro-text-to-speech-mcp/server.py
```

Claude Desktop does not read this. Add the server to `claude_desktop_config.json` as described in the README (section "Connect it to Claude").

Restart Claude, then check that `tts` is listed and connected (`/mcp` in Claude Code).

## 4. Install the plugins

Add the marketplace once. Option A, from GitHub (after the branch is merged into `master`), in Claude Code:

```
/plugin marketplace add GolovchenkoA/kokoro-text-to-speech-mcp
```

Option B, from the local clone from step 2 (no GitHub needed):

```
/plugin marketplace add /absolute/path/to/kokoro-text-to-speech-mcp
```

Then install what you want:

```
/plugin install larkspeak@larkspeak            # the skill
/plugin install larkspeak-buttons@larkspeak    # the buttons (optional, can be added or removed later)
```

Restart Claude if it asks you to.

## 5. Check that it works

1. Skill: ask the agent "read your last answer aloud". The `larkspeak` skill should trigger and call `start_speech`.
2. Buttons (only if installed): a row of small icons (read aloud, pause, continue, stop) appears under each reply. Hover an icon to see its name. Press the read aloud icon and the reply is spoken.
3. With voice control on (the default), say "pause speech", "continue speech", "stop speech" or "status speech".

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| No icons under replies | `larkspeak-buttons` is not installed (the `larkspeak` skill does not add buttons) or Claude was not restarted. Run `/plugin` and check that `larkspeak-buttons` is enabled. |
| Icon press shows "server is not connected" | The MCP server is not registered under the name `tts`, or it failed to start. Repeat step 3 and check `/mcp`. |
| Server fails to start | The command must be the venv's Python with absolute paths. See "Troubleshooting" in the README. |
| No sound, or only English sounds right | `espeak-ng` missing, or a voice that does not match the text language. |
| Voice commands do nothing | Microphone permission denied, or voice control disabled with `TTS_VOICE_CONTROL_ENABLED=0`. |

## Update and remove

- Update the server: `git pull`, then `python -m pip install -r requirements.txt` with the project's virtual environment active (or through `.venv`'s Python), then restart Claude. Never install into the system Python.
- Update the plugins: `/plugin marketplace update larkspeak`, then update `larkspeak` and `larkspeak-buttons`.
- Remove only the buttons: `/plugin uninstall larkspeak-buttons@larkspeak`. Remove the skill: `/plugin uninstall larkspeak@larkspeak`. Remove the server: `claude mcp remove tts`.

## Notes

- The plugin ships no `.mcp.json` yet, because the server is not installable with one command. After the server is published to PyPI, add `.mcp.json` to `plugins/larkspeak/` so a single plugin install starts it. See step 3 of `docs/TODO/updates.md`.
- If the MCP server name `tts` is changed (`MCPServer("tts")` in `server.py`), change `SERVER` in `plugins/larkspeak-buttons/hooks/register.tsx`, the name in this file, and the name in `plugins/larkspeak/skills/larkspeak/SKILL.md`.
- Commands for installing the plugin were written from the plugin documentation and have not been run on a clean computer.
