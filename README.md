# kokoro-text-to-speech-mcp

MCP server that gives Claude Desktop (or any MCP client) a local, offline text-to-speech tool using Kokoro-82M. It speaks text on your speakers, can be paused, resumed and stopped, and can optionally be controlled by voice.

## Tools

- `start_speech(text, voice="af_heart", speed=1.0)` → speaks the text on the local speakers and returns immediately. Text only (no file paths or URLs); audio is generated and played entirely in memory via `sounddevice`, nothing is written to disk. Starting a new speech stops the current one
- `pause_speech()` / `resume_speech()` → hold and continue the current speech (takes effect within ~0.1 s)
- `stop_speech()` → interrupt the current speech and discard the rest
- `speech_status()` → `idle`, `playing`, `paused`, `finished`, `stopped` or `error`
- `list_voices()` → voice IDs grouped by language

Prompt:
- `speak-last-reply [messages]` → pick it from the prompt/slash-command menu to have Claude read recent messages aloud. `messages` is free text such as `last 5 messages` or `last fifth messages`; the default is the last message (Claude's previous answer). One message is one message sent by you or by Claude, counted separately. The model collects them oldest first and calls `start_speech` once with them unchanged. When several messages are read, each starts with its owner label, `User message:` or `Assistant message:`; a single message has no label. The prompt adds no limits (the server still rejects text over 20,000 characters). The model follows these instructions; the server cannot read the conversation itself, so the spoken text is only as exact as the model's copy.

The older `speak` (save to WAV) and `play_file` tools were removed; they remain in git history (commit `3587dc0`).

## Requirements

| Needed | Notes |
|---|---|
| Python **3.14** (or 3.12) | `.python-version` pins 3.14. 3.13 is not supported by `kokoro`; 3.12 works without the workaround flag below |
| ~3 GB free disk | PyTorch plus packages (~2 GB), Kokoro model (~330 MB), optional Vosk model (~40 MB) |
| Internet on first run | Kokoro model is downloaded from Hugging Face on the first `start_speech`; later runs are fully offline |
| A speaker / output device | Audio plays on the machine that runs the server |
| `espeak-ng` | System package, see step 3 |
| Linux only: PortAudio | `sudo apt install libportaudio2` (bundled on Windows/macOS) |
| Optional: a microphone | Only for voice control |

No GPU is needed; CPU is fast enough. No API keys.

## Setup on a new computer

### 1. Get the code

```bash
git clone https://github.com/GolovchenkoA/kokoro-text-to-speech-mcp.git
cd kokoro-text-to-speech-mcp
```

### 2. Create a virtual environment and install dependencies

`kokoro==0.9.4` declares `requires-python <3.13`, so on Python 3.14 pip needs `--ignore-requires-python`. `--only-binary=:all:` stops pip from trying to compile spaCy/blis from source (which fails on Windows). `vosk` (voice control) needs `srt`, which has no wheel, so install `srt` first.

**Windows (PowerShell)**

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install srt
python -m pip install --ignore-requires-python --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

**Linux / macOS**

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install srt
python -m pip install --ignore-requires-python --only-binary=:all: --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

- The `--extra-index-url` line installs the smaller CPU-only PyTorch. Drop it for the default build (or if you want CUDA).
- If installation fails on 3.14, use Python 3.12 instead (`py -3.12` / `python3.12`); the code is unchanged and `--ignore-requires-python` is no longer needed.
- Japanese and Chinese voices need extras: `python -m pip install --ignore-requires-python "misaki[ja]"` / `"misaki[zh]"`.

### 3. Install espeak-ng

Used for out-of-dictionary words and non-English languages.

- Windows: install the `.msi` from https://github.com/espeak-ng/espeak-ng/releases
- macOS: `brew install espeak-ng`
- Ubuntu/Debian: `sudo apt install espeak-ng`

### 4. Check the installation

```bash
python -c "import mcp.server.mcpserver, sounddevice, vosk, kokoro; print('imports ok')"
```

(Run it with the venv active, or call `.venv\Scripts\python.exe` / `.venv/bin/python` directly.) Optional: open the server in the MCP Inspector with `npx @modelcontextprotocol/inspector <path-to-venv-python> server.py`.

### 5. Connect to Claude Desktop

Edit `claude_desktop_config.json` (Claude Desktop → Settings → Developer → Edit Config):
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`

Use **absolute paths** to the venv's Python and to `server.py`. Do not rely on `python` from PATH: Claude Desktop must use the interpreter that has the packages installed.

**Windows** (interpreter is `.venv\Scripts\python.exe`, there is no `bin` folder; backslashes must be doubled in JSON)

```json
{
  "mcpServers": {
    "kokoro-tts": {
      "command": "C:\\path\\to\\kokoro-text-to-speech-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\kokoro-text-to-speech-mcp\\server.py"],
      "env": {
        "KOKORO_DEFAULT_VOICE": "af_heart",
        "KOKORO_WAKEWORD": "1"
      }
    }
  }
}
```

**macOS** (interpreter is `.venv/bin/python`)

```json
{
  "mcpServers": {
    "kokoro-tts": {
      "command": "/absolute/path/to/kokoro-text-to-speech-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/kokoro-text-to-speech-mcp/server.py"],
      "env": {
        "KOKORO_DEFAULT_VOICE": "af_heart",
        "KOKORO_WAKEWORD": "1"
      }
    }
  }
}
```

Leave out `"KOKORO_WAKEWORD": "1"` if you do not want microphone voice control. If you already have other servers under `mcpServers`, add only the `"kokoro-tts"` entry.

### 6. Restart and try it

Fully quit Claude Desktop (tray/menu bar icon → Quit, not just close the window) and start it again. Then ask, for example:

> Read this paragraph aloud with bm_george: ...

The first request is slow: it downloads and loads the Kokoro model (~330 MB). Then try "pause", "continue" and "stop".

## Voice control (optional)

Set `KOKORO_WAKEWORD=1` and the server listens on the microphone for exactly four phrases:

| Say | Does |
|---|---|
| "pause speech" | `pause_speech` |
| "continue speech" | `resume_speech` |
| "stop speech" | `stop_speech` |
| "status speech" | says aloud whether speech is playing, paused, finished, stopped or idle |

It can do nothing else. Recognition uses [Vosk](https://alphacephei.com/vosk/) restricted to those phrases and acts only when the whole utterance is exactly one of them. Audio is processed in memory and never stored or sent anywhere. Off by default. English only.

- A voice activity gate (`KOKORO_VAD`) keeps Vosk idle until someone speaks. Flow details: [docs/this-program-STT-flow.md](docs/this-program-STT-flow.md).
- First use downloads the small English model (~40 MB) to `~/.cache/vosk`; set `KOKORO_VOSK_MODEL` to a local model folder to avoid the download (e.g. for offline machines).
- `KOKORO_MIC_DEVICE` selects the input device (name or index).
- Use headphones if you can: the speakers' own output reaches the microphone and can cause missed commands.
- The OS must allow microphone access for the process that runs the server (Windows: Settings → Privacy → Microphone; macOS: System Settings → Privacy & Security → Microphone).

## Several server copies (primary and secondary)

Claude Desktop starts the server more than once (one copy for chat, one for Cowork/Code sessions). To avoid duplicate speech and duplicate answers to voice commands, the copies share one backend:

- The **first** copy is the **primary**: it loads the models and owns the speakers, the microphone and the voice listener.
- Every later copy is a **secondary**: it forwards `start_speech`, `pause_speech`, `resume_speech`, `stop_speech` and `speech_status` to the primary over a private local channel (a named pipe on Windows, a Unix socket elsewhere, protected by a random key in `~/.kokoro_mcp/ipc.key`).
- So there is one speech, one listener and one answer, whichever copy a client talks to.
- If the primary exits, a secondary takes over on its next request (and starts the voice listener).
- When a client closes the server, that copy stops its speech and listener and releases the channel.

The log (stderr, visible in Claude Desktop's MCP log) shows the roles:

```
Instance process 9760 is the primary
Instance process 1888 is a secondary: speech is redirected to process 9760 (primary)
Speech redirected from process 1888 (secondary) to process 9760 (primary): start
```

The process IDs are those of the Python interpreter (on Windows the venv launcher shows up as an extra parent `python.exe`). Set `KOKORO_SHARED_INSTANCE=0` to make every copy work on its own.

## Project layout

| Path | Responsibility |
|---|---|
| `server.py` | Entry point: builds the components, registers the tools, runs the server |
| `mcp_tools.py` | The `@mcp.tool()` definitions (thin adapters over `SpeechService`) |
| `kokoro_mcp/config.py` | Constants and `Settings` (environment variables) |
| `kokoro_mcp/voices.py` | Language and voice catalogue |
| `kokoro_mcp/synthesis.py` | `SpeechSynthesizer`: text to audio chunks with Kokoro |
| `kokoro_mcp/speech.py` | `SpeechSession` (play, pause, resume, stop) and `SpeechService` (owns the active session) |
| `kokoro_mcp/audio.py` | Speaker and microphone access (`sounddevice`) |
| `kokoro_mcp/voice_control/` | `EnergyGate` (VAD), `VoiceCommandHandler`, `StatusAnnouncer`, `VoiceControlListener` |
| `kokoro_mcp/instance.py` | `InstanceManager`: primary/secondary election, delegation, takeover, shutdown |
| `kokoro_mcp/runtime.py` | `PrimaryRuntime`: the components only the primary runs |
| `kokoro_mcp/ipc.py` | Local endpoint: `PrimaryServer`, `RemoteSpeechService`, key and address handling |

## Tests

End-to-end tests run a real in-process MCP client against the server, with the audio device, Kokoro and Vosk replaced by fakes (no model download, speakers or microphone needed):

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

`tests/test_tools_e2e.py` covers the tools (start, pause, resume, stop, status, validation, errors) and `tests/test_voice_control.py` covers the microphone commands.

## Configuration (env vars)

Set these in the `env` block of the Claude Desktop config.

| Variable | Default | Purpose |
|---|---|---|
| `KOKORO_DEFAULT_VOICE` | `af_heart` | Voice used when none is given |
| `KOKORO_DEVICE` | auto | `cpu`, `cuda` or `mps` |
| `KOKORO_WAKEWORD` | off | `1` enables microphone voice control |
| `KOKORO_VOSK_MODEL` | auto-download | Path to a local Vosk model folder |
| `KOKORO_MIC_DEVICE` | system default | Microphone name or index |
| `KOKORO_VAD` | `energy` | `energy` runs Vosk only while someone is speaking; `off` feeds it all audio |
| `KOKORO_VAD_THRESHOLD` | `500` | Speech level (RMS, int16 scale) that opens the gate; lower it if commands are missed |
| `KOKORO_SHARED_INSTANCE` | `1` | `0` disables primary/secondary sharing: every server copy works on its own |
| `KOKORO_IPC_DIR` | `~/.kokoro_mcp` | Where the shared key for the local channel is stored |

## Languages

Voice IDs start with a language letter and the text must match it: `a` American English, `b` British English, `e` Spanish, `f` French, `h` Hindi, `i` Italian, `j` Japanese, `p` Brazilian Portuguese, `z` Mandarin Chinese. Kokoro has no Polish voice. Call `list_voices` for the IDs.

## Troubleshooting

Claude Desktop logs: `%APPDATA%\Claude\logs\mcp-server-kokoro-tts.log` (Windows) or `~/Library/Logs/Claude/mcp-server-kokoro-tts.log` (macOS).

| Symptom | Fix |
|---|---|
| `No module named 'mcp.server.fastmcp'` | An old checkout/`mcp` 1.x mix-up. The code needs `mcp` 2.x: `python -m pip install -r requirements.txt` in the venv |
| `No matching distribution found for srt` | Run `python -m pip install srt` before the main install (step 2) |
| pip tries to build spaCy / blis and fails | Add `--only-binary=:all:` or use Python 3.12 |
| `requires a different Python` for kokoro | Add `--ignore-requires-python` (Python 3.14) or use Python 3.12 |
| Server does not start in Claude Desktop | Check that `command` is the venv's Python (absolute path) and the paths in `args` exist |
| No sound | Check the default output device. On Linux install `libportaudio2` |
| Non-English text sounds wrong or errors | Install `espeak-ng` and use a voice that matches the text language |
| Two answers to a voice command | Update to this version: only the primary instance listens. With `KOKORO_SHARED_INSTANCE=0` every copy listens |
| `primary instance is not reachable` error | The primary exited; retry the request (a secondary takes over automatically) |
| `Voice control stopped` in the log | `vosk` not installed, no microphone, or microphone permission denied |
| Voice commands are missed | Use headphones, speak the phrase alone and clearly, or set `KOKORO_MIC_DEVICE` |
