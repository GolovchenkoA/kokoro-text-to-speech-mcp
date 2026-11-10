# kokoro-mcp

Minimal MCP server that gives Claude Desktop a local text-to-speech tool using Kokoro-82M.

Tools:
- `speak(text, voice="af_heart", speed=1.0, filename=None)` → writes a 24 kHz WAV and returns its path
- `list_voices()` → voice IDs grouped by language

## Install (Python 3.14)

`kokoro==0.9.4` declares `requires-python <3.13`, so pip refuses it on 3.14 by default.
Bypass the check (whether all transitive deps — torch, misaki, spaCy — have 3.14 wheels on your platform is the part to verify):

```bash
python3.14 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install --ignore-requires-python -r requirements.txt
```

CPU-only torch (smaller download):

```bash
pip install --ignore-requires-python --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

System dependency — espeak-ng (used for out-of-dictionary words and non-English languages):
- macOS: `brew install espeak-ng`
- Ubuntu/Debian: `sudo apt install espeak-ng`
- Windows: install the `.msi` from https://github.com/espeak-ng/espeak-ng/releases

Japanese and Chinese voices need extras: `pip install --ignore-requires-python "misaki[ja]"` / `"misaki[zh]"`.

If 3.14 installation fails, the same code runs unchanged on Python 3.12.

## Test locally

```bash
mcp dev server.py      # opens the MCP Inspector
```

The first `speak` call downloads the model (~330 MB) from Hugging Face.

## Connect to Claude Desktop

Edit `claude_desktop_config.json`:
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "kokoro-tts": {
      "command": "/absolute/path/to/kokoro-mcp/.venv/bin/python",
      "args": ["/absolute/path/to/kokoro-mcp/server.py"],
      "env": {
        "KOKORO_OUTPUT_DIR": "~/kokoro_output",
        "KOKORO_DEFAULT_VOICE": "af_heart"
      }
    }
  }
}
```

On Windows use `C:\\path\\to\\kokoro-mcp\\.venv\\Scripts\\python.exe`. Restart Claude Desktop, then ask:
"Read this paragraph aloud with bm_george and save it as intro.wav".

## Configuration (env vars)

| Variable | Default | Purpose |
|---|---|---|
| `KOKORO_OUTPUT_DIR` | `~/kokoro_output` | Where WAV files are written |
| `KOKORO_DEFAULT_VOICE` | `af_heart` | Voice used when none is given |
| `KOKORO_DEVICE` | auto | `cpu`, `cuda` or `mps` |

Note: Kokoro has no Polish voice; supported languages are EN (US/UK), ES, FR, HI, IT, JA, PT-BR, ZH.
