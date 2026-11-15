# Larkspeak

MCP server that gives Claude Desktop (or any MCP client) a local, offline text-to-speech tool. It speaks text on your speakers, can be paused, resumed and stopped, and can optionally be controlled by voice.

## Speech models

Which text-to-speech model speaks is decided by **`models.json`** (next to `server.py`; point `TTS_MODELS_FILE` at another file to use your own). The file lists the models, the languages each one speaks, the voices for each language, the default model, and the default voice for every model and language. Nothing in the code names a model, so switching the default model, or adding a model that uses an existing engine class, is a change to that file only. A model family with a new engine needs one new engine class and a line in the file, see [docs/ADDING_A_MODEL.md](docs/ADDING_A_MODEL.md).

Models shipped in `models.json`:

| Model id | Model | Languages | Needs |
|---|---|---|---|
| `kokoro` (default) | Kokoro-82M | American and British English, Spanish, French, Hindi, Italian, Japanese, Brazilian Portuguese, Mandarin Chinese | `requirements-kokoro.txt` (also `requirements.txt`), `espeak-ng` |
| `qwen3` | Qwen3-TTS 0.6B, preset voices only | English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish, Italian (any language with "auto") | `requirements-qwen3.txt` |

When a request names no model, the server uses the default model, or the first model that has the requested voice and language. A model is loaded only when it is first used. Every model must meet the rules in [docs/APP_REQUIREMENTS.md](docs/APP_REQUIREMENTS.md): commercial-use license, audio only in memory, and CPU fallback.

**Devices.** Each model runs on the GPU when there is one (`"device": "auto"` in the file, or `TTS_DEVICE`) and on the CPU otherwise. A requested GPU that is missing, or a GPU that fails to load a model, falls back to the CPU with a log message.

## Tools

- `start_speech(text, voice=None, speed=1.0, model=None, language=None)` → speaks the text on the local speakers and returns immediately. Text only (no file paths or URLs); audio is generated and played entirely in memory via `sounddevice`, nothing is written to disk. Starting a new speech stops the current one. `voice`, `model` and `language` are optional: what is left out is chosen from the models file (see below). The result also tells how to pause, continue and stop it (and lists the voice commands when voice control is on)
- `pause_speech()` / `resume_speech()` → hold and continue the current speech (takes effect within ~0.1 s)
- `stop_speech()` → interrupt the current speech and discard the rest
- `speech_status()` → `idle`, `playing`, `paused`, `finished`, `stopped` or `error`
- `list_models()` → the models with the languages and voices of each, and the default model

Prompt:
- `speak-last-reply [messages]` → pick it from the prompt/slash-command menu to have Claude read recent messages aloud. `messages` is free text such as `last 5 messages` or `last fifth messages`; the default is the last message (Claude's previous answer). One message is one message sent by you or by Claude, counted separately. The model collects them oldest first and calls `start_speech` once with them unchanged. When several messages are read, each starts with its owner label, `User message:` or `Assistant message:`; a single message has no label. The prompt adds no limits (the server still rejects text over 20,000 characters). The model follows these instructions; the server cannot read the conversation itself, so the spoken text is only as exact as the model's copy.

The older `speak` (save to WAV) and `play_file` tools were removed; they remain in git history (commit `3587dc0`).

## Requirements

| Needed | Notes |
|---|---|
| Python **3.14** (or 3.12) | `.python-version` pins 3.14. 3.13 is not supported by the engine package (`kokoro`); 3.12 works without the workaround flag below |
| ~3 GB free disk | PyTorch plus packages (~2 GB), speech model (~330 MB), Vosk model for voice control (~40 MB) |
| Internet on first run | The speech model is downloaded from Hugging Face on the first `start_speech`; later runs are fully offline |
| A speaker / output device | Audio plays on the machine that runs the server |
| `espeak-ng` | System package, see step 3 |
| Linux only: PortAudio | `sudo apt install libportaudio2` (bundled on Windows/macOS) |
| A microphone | For voice control, which is on by default. The server works without one (the listener just logs an error) |

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
- Requirement files: `requirements-base.txt` (server, audio, voice control: no model), `requirements-kokoro.txt` and `requirements-qwen3.txt` (base plus one model). `requirements.txt` is base plus Kokoro, the default model, so the commands above install it. Install only the models you use; a model that is not installed is never imported.
- Qwen3-TTS only, or in addition to Kokoro (more languages): `python -m pip install -r requirements-qwen3.txt`; to make it the default, set `"default_model": "qwen3"` in `models.json`. Its weights are about 2.3 GB, see "Download the models in advance". Checked with the real model on a CPU (Windows, Python 3.14): it generates English and German speech and its output rate is 24 kHz. On that CPU it generated audio about four times slower than real time, so speech has pauses between sentences; a GPU is recommended for it. Not checked: a GPU, macOS, Linux, and installing it in the same environment as Kokoro (the dependency resolver reports no conflict).
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
    "tts": {
      "command": "C:\\path\\to\\kokoro-text-to-speech-mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\kokoro-text-to-speech-mcp\\server.py"],
      "env": {
        "TTS_DEVICE": "auto"
      }
    }
  }
}
```

**macOS** (interpreter is `.venv/bin/python`)

```json
{
  "mcpServers": {
    "tts": {
      "command": "/absolute/path/to/kokoro-text-to-speech-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/kokoro-text-to-speech-mcp/server.py"],
      "env": {
        "TTS_DEVICE": "auto"
      }
    }
  }
}
```

Voice control is on by default; add `"TTS_VOICE_CONTROL_ENABLED": "0"` to `env` to turn it off. If you already have other servers under `mcpServers`, add only the `"tts"` entry.

### 6. Restart and try it

Fully quit Claude Desktop (tray/menu bar icon → Quit, not just close the window) and start it again. Then ask, for example:

> Read this paragraph aloud with bm_george: ...

The first request is slow: it downloads and loads the speech model (~330 MB). Then try "pause", "continue" and "stop".

## Download the models in advance

Models are downloaded the first time they are used, which makes the first speech wait (minutes for the larger ones). To download them before that, for example while you have a good connection, run this in the virtual environment:

```bash
python -m tts_mcp.download                  # the default model (Kokoro, about 330 MB)
python -m tts_mcp.download qwen3            # one named model (Qwen3-TTS, about 2.3 GB)
python -m tts_mcp.download --all            # every model in models.json
python -m tts_mcp.download --voice-control  # also the voice-control model (about 40 MB); can be combined with the others
```

On Windows use `.venv\Scripts\python.exe` in place of `python` if the environment is not activated. The command reads `models.json` (or `TTS_MODELS_FILE`) and fetches the `repo` of each model's `options`, so a model you add is downloaded the same way.

- **Where the files go.** Hugging Face models go to `~/.cache/huggingface/hub` (`C:\Users\<you>\.cache\huggingface\hub` on Windows; set `HF_HOME` to move it). Every project and virtual environment on the machine shares this cache, so another project that loads the same model does not download it again. The voice-control model goes to `~/.cache/vosk`.
- **Check it works offline.** After the download, set `HF_HUB_OFFLINE=1` in the server's `env` to make sure nothing is fetched at run time.
- **A computer without internet.** Download on a connected computer, copy the cache folders above to the same place on the other computer, and set `HF_HUB_OFFLINE=1`. Voice control can also use a local Vosk model folder (`TTS_VOSK_MODEL`).
- **Windows symlink warning.** Hugging Face may warn that symlinks are not supported. The files still download; they just use more disk space. Turning on Windows Developer Mode removes the warning.

## Voice control

By default the server listens on the microphone for exactly four phrases (set `TTS_VOICE_CONTROL_ENABLED=0` to turn it off):

| Say | Does |
|---|---|
| "pause speech" | `pause_speech` |
| "continue speech" | `resume_speech` |
| "stop speech" | `stop_speech` |
| "status speech" | says aloud whether speech is playing, paused, finished, stopped or idle |

It can do nothing else. Recognition uses [Vosk](https://alphacephei.com/vosk/) restricted to those phrases and acts only when the whole utterance is exactly one of them. Audio is processed in memory and never stored or sent anywhere. On by default. English only. Without a microphone or `vosk`, the listener logs an error and the server keeps working without voice control.

- A voice activity gate (`TTS_VAD`) keeps Vosk idle until someone speaks. Flow details: [docs/this-program-STT-flow.md](docs/this-program-STT-flow.md).
- First use downloads the small English model (~40 MB) to `~/.cache/vosk`; set `TTS_VOSK_MODEL` to a local model folder to avoid the download (e.g. for offline machines).
- `TTS_MIC_DEVICE` selects the input device (name or index).
- Use headphones if you can: the speakers' own output reaches the microphone and can cause missed commands.
- The OS must allow microphone access for the process that runs the server (Windows: Settings → Privacy → Microphone; macOS: System Settings → Privacy & Security → Microphone).

## Several server copies (primary and secondary)

Claude Desktop starts the server more than once (one copy for chat, one for Cowork/Code sessions). To avoid duplicate speech and duplicate answers to voice commands, the copies share one backend:

- The **first** copy is the **primary**: it loads the models and owns the speakers, the microphone and the voice listener.
- Every later copy is a **secondary**: it forwards `start_speech`, `pause_speech`, `resume_speech`, `stop_speech` and `speech_status` to the primary over a private local channel (a named pipe on Windows, a Unix socket elsewhere, protected by a random key in `~/.tts_mcp/ipc.key`).
- So there is one speech, one listener and one answer, whichever copy a client talks to.
- If the primary exits, a secondary takes over on its next request (and starts the voice listener).
- When a client closes the server, that copy stops its speech and listener and releases the channel.

The log (stderr, visible in Claude Desktop's MCP log) shows the roles:

```
Instance process 9760 is the primary
Instance process 1888 is a secondary: speech is redirected to process 9760 (primary)
Speech redirected from process 1888 (secondary) to process 9760 (primary): start
```

The process IDs are those of the Python interpreter (on Windows the venv launcher shows up as an extra parent `python.exe`). Set `TTS_SHARED_INSTANCE=0` to make every copy work on its own.

## Project layout

| Path | Responsibility |
|---|---|
| `server.py` | Entry point: builds the components, registers the tools, runs the server |
| `mcp_tools.py` | The `@mcp.tool()` definitions (thin adapters over `SpeechService`) |
| `tts_mcp/config.py` | Constants and `Settings` (environment variables) |
| `models.json` | The models file: models, engines, languages, voices, defaults |
| `tts_mcp/catalog.py` | Reads and validates the models file; picks model, language and voice for a request |
| `tts_mcp/engines/` | One adapter class per model family (`kokoro.py`, `qwen3.py`), the engine contract and the factory |
| `tts_mcp/devices.py` | GPU detection and the CPU fallback |
| `tts_mcp/download.py` | `python -m tts_mcp.download`: fetch the models ahead of time |
| `tts_mcp/synthesis.py` | `SpeechSynthesizer`: routes a request to the engine of the selected model (knows no model) |
| `tts_mcp/speech.py` | `SpeechSession` (play, pause, resume, stop) and `SpeechService` (owns the active session) |
| `tts_mcp/audio.py` | Speaker and microphone access (`sounddevice`) |
| `tts_mcp/voice_control/` | `EnergyGate` (VAD), `VoiceCommandHandler`, `StatusAnnouncer`, `VoiceControlListener` |
| `tts_mcp/instance.py` | `InstanceManager`: primary/secondary election, delegation, takeover, shutdown |
| `tts_mcp/runtime.py` | `PrimaryRuntime`: the components only the primary runs |
| `tts_mcp/ipc.py` | Local endpoint: `PrimaryServer`, `RemoteSpeechService`, key and address handling |

## Tests

End-to-end tests run a real in-process MCP client against the server, with the audio device, the speech engine and Vosk replaced by fakes (no model download, speakers or microphone needed):

```bash
python -m pip install -r requirements-dev.txt
python -m pytest
```

`tests/test_tools_e2e.py` covers the tools (start, pause, resume, stop, status, validation, errors) and `tests/test_voice_control.py` covers the microphone commands.

## Configuration (env vars)

Set these in the `env` block of the Claude Desktop config.

| Variable | Default | Purpose |
|---|---|---|
| `TTS_MODELS_FILE` | `models.json` next to `server.py` | The models file: models, languages, voices, defaults |
| `TTS_DEVICE` | per model (`auto`) | `cpu`, `cuda` or `mps` for all models; falls back to the CPU when not available |
| `TTS_VOICE_CONTROL_ENABLED` | on | `0` (or `false`, `no`, `off`) turns microphone voice control off |
| `TTS_VOSK_MODEL` | auto-download | Path to a local Vosk model folder |
| `TTS_MIC_DEVICE` | system default | Microphone name or index |
| `TTS_VAD` | `energy` | `energy` runs Vosk only while someone is speaking; `off` feeds it all audio |
| `TTS_VAD_THRESHOLD` | `500` | Speech level (RMS, int16 scale) that opens the gate; lower it if commands are missed |
| `TTS_SHARED_INSTANCE` | `1` | `0` disables primary/secondary sharing: every server copy works on its own |
| `TTS_IPC_DIR` | `~/.tts_mcp` | Where the shared key for the local channel is stored |

## Languages and voices

Call `list_models` for the exact languages and voices of every model. Kokoro voice IDs are language specific (`af_heart` American English, `bm_george` British English, `ff_siwis` French, and so on). Qwen3 voices (`Ryan`, `Aiden`, `Vivian`, `Serena`, `Uncle_Fu`, `Dylan`, `Eric`, `Ono_Anna`, `Sohee`) can speak every language the model supports; pass `language` (for example `"de"`) so the text is read in that language. No shipped model has a Polish voice.

**Choosing the language.** Pass `language` (for example `"ru"`) whenever you know it; the server cannot tell German from English, because both are written in Latin letters. Without `language` or `voice`, the default model's default voice reads the text. A text in another writing system is detected (Cyrillic, Chinese, Japanese, Korean, Devanagari, Greek, Arabic and so on):

- with no `language`, the first model that speaks a language of that script is used (a Russian text goes to Qwen3 when Kokoro has no Russian);
- a voice or language that cannot read the text is refused with an error that the agent sees, instead of being read wrongly;
- if the chosen model's package is not installed, `speech_status` reports `error` with the install command.

## Troubleshooting

Claude Desktop logs: `%APPDATA%\Claude\logs\mcp-server-tts.log` (Windows) or `~/Library/Logs/Claude/mcp-server-tts.log` (macOS).

| Symptom | Fix |
|---|---|
| `No module named 'mcp.server.fastmcp'` | An old checkout/`mcp` 1.x mix-up. The code needs `mcp` 2.x: `python -m pip install -r requirements.txt` in the venv |
| `No matching distribution found for srt` | Run `python -m pip install srt` before the main install (step 2) |
| pip tries to build spaCy / blis and fails | Add `--only-binary=:all:` or use Python 3.12 |
| `requires a different Python` for the engine package (`kokoro`) | Add `--ignore-requires-python` (Python 3.14) or use Python 3.12 |
| Server does not start in Claude Desktop | Check that `command` is the venv's Python (absolute path) and the paths in `args` exist |
| No sound | Check the default output device. On Linux install `libportaudio2` |
| Non-English text sounds wrong or errors | Install `espeak-ng` and use a voice that matches the text language |
| Two answers to a voice command | Update to this version: only the primary instance listens. With `TTS_SHARED_INSTANCE=0` every copy listens |
| `primary instance is not reachable` error | The primary exited; retry the request (a secondary takes over automatically) |
| `Voice control stopped` in the log | `vosk` not installed, no microphone, or microphone permission denied |
| Voice commands are missed | Use headphones, speak the phrase alone and clearly, or set `TTS_MIC_DEVICE` |
