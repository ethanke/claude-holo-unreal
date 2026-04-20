"""Entry point for `python -m holo_unreal` — delegates to the CLI."""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
