"""Allow running the CLI as ``python -m secondbrain`` (no PATH setup needed)."""

from __future__ import annotations

from secondbrain.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
