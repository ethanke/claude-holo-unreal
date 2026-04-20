"""Environment + .env loader shared by CLI, library and MCP server.

Zero dependencies — parses KEY=VALUE pairs, ignores comments and blanks.
"""
from __future__ import annotations

import os
from pathlib import Path

_LOADED = False


def load_env(path: str | os.PathLike | None = None) -> None:
    """Read a .env file and populate os.environ (without overwriting).

    Search order:
      1. Explicit `path` argument.
      2. `$HOLO_UNREAL_ENV`.
      3. `./.env` in the current working directory.
      4. `<package_root>/../.env` (repo checkout layout).
    """
    global _LOADED
    if _LOADED and path is None:
        return

    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    if os.environ.get("HOLO_UNREAL_ENV"):
        candidates.append(Path(os.environ["HOLO_UNREAL_ENV"]))
    candidates.append(Path.cwd() / ".env")
    candidates.append(Path(__file__).resolve().parent.parent / ".env")

    for p in candidates:
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
        _LOADED = True
        return

    _LOADED = True


DEFAULT_BASE_URL = "https://api.hcompany.ai/v1/"
DEFAULT_MODEL = "holo3-35b-a3b"
DEFAULT_WINDOW_TITLE = "Unreal Editor"


def hai_api_key() -> str | None:
    load_env()
    return os.environ.get("HAI_API_KEY")


def hai_base_url() -> str:
    load_env()
    return os.environ.get("HAI_MODEL_URL", DEFAULT_BASE_URL)


def hai_model() -> str:
    load_env()
    return os.environ.get("HAI_MODEL_NAME", DEFAULT_MODEL)


def default_project() -> str | None:
    load_env()
    return os.environ.get("UE_PROJECT")


def default_window_title() -> str:
    load_env()
    return os.environ.get("HOLO_UNREAL_WINDOW_TITLE", DEFAULT_WINDOW_TITLE)
