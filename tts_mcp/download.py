"""Download model files ahead of time, so the first speech does not wait for them.

    python -m tts_mcp.download                 # the default model
    python -m tts_mcp.download qwen3           # named models
    python -m tts_mcp.download --all           # every model in the models file
    python -m tts_mcp.download --voice-control # also the voice-control (Vosk) model

Models are read from the models file; a model with an ``options.repo`` entry is fetched from Hugging
Face into the shared cache (``~/.cache/huggingface``), where the server and any other project find it.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from tts_mcp.catalog import CatalogError, load_catalog
from tts_mcp.config import Settings


def _download_repo(repo: str) -> str:
    from huggingface_hub import snapshot_download  # imported here: only this command needs it

    return snapshot_download(repo_id=repo)


def _download_voice_control_model(path: str | None) -> None:
    if path:
        print(f"Voice control uses the local model in {path}: nothing to download.")
        return
    import vosk  # the small English model is fetched when the model is created

    print("Downloading the voice-control model (about 40 MB) ...")
    vosk.Model(lang="en-us")
    print("Voice-control model ready.")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tts_mcp.download", description=__doc__.split("\n")[0])
    parser.add_argument("models", nargs="*", help="model ids from the models file (default: the default model)")
    parser.add_argument("--all", action="store_true", help="download every enabled model in the models file")
    parser.add_argument("--voice-control", action="store_true", help="also download the voice-control model")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    try:
        catalog = load_catalog(settings.resolved_models_file, include_disabled=True)  # a disabled model can be fetched before it is enabled
    except CatalogError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    enabled = [model_id for model_id, spec in catalog.models.items() if spec.enabled]
    ids = args.models or (enabled if args.all else [catalog.default_model])
    unknown = [model_id for model_id in ids if model_id not in catalog.models]
    if unknown:
        print(f"error: unknown model(s): {', '.join(unknown)}. Known: {', '.join(catalog.models)}", file=sys.stderr)
        return 2

    failed = False
    for model_id in ids:
        spec = catalog.models[model_id]
        repo = spec.options.get("repo")
        if not repo:
            print(f"{model_id}: no 'repo' in its options, nothing to download.")
            continue
        print(f"{model_id}: downloading {repo} ...")
        try:
            folder = _download_repo(str(repo))
        except Exception as exc:  # network, disk or access problems: report and go on with the others
            print(f"{model_id}: failed: {exc}", file=sys.stderr)
            failed = True
            continue
        print(f"{model_id}: ready in {folder}")

    if args.voice_control:
        try:
            _download_voice_control_model(settings.vosk_model)
        except Exception as exc:
            print(f"voice control: failed: {exc}", file=sys.stderr)
            failed = True

    print(f"Models are cached in {os.environ.get('HF_HOME') or '~/.cache/huggingface'} and shared with other projects.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
