"""Allow running the CLI as ``python -m second_brain`` (no PATH setup needed)."""

from __future__ import annotations

from second_brain.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
