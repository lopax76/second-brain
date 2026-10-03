"""Cross-process lock for writes to a graph store (stdlib only, Windows and POSIX).

Several agents (Claude Code, Codex, the CLI, a git hook) can touch the same store at once. Each
would otherwise rebuild on its own and the last atomic write would win — wasted minutes on a big
tree and, worse, two builds racing on ``extract.json``/``signature.json``. A store is therefore
written by one process at a time:

* the lock is an OS-level byte-range lock on ``<store>/write.lock`` (``msvcrt`` on Windows,
  ``fcntl`` elsewhere), so it vanishes by itself if the holder dies — no stale lock files;
* acquisition is **non-blocking by default**: a reader that finds a rebuild already running does
  not queue behind it, it serves the graph it has and says so;
* the holder writes who it is (pid, agent, since) next to the lock, for the warning text.

Different stores (different projects) have different lock files, so they never wait on each other.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_IS_WINDOWS = os.name == "nt"
if _IS_WINDOWS:  # pragma: no cover - platform branch
    import msvcrt
else:  # pragma: no cover - platform branch
    import fcntl


class Busy(Exception):
    """Raised when the store is being written by another process."""

    def __init__(self, holder: dict[str, Any] | None):
        self.holder = holder or {}
        who = self.holder.get("agent") or "un altro processo"
        since = self.holder.get("since", "")
        pid = self.holder.get("pid", "?")
        super().__init__(f"store in scrittura da {who} (pid {pid}) {since}".strip())


def agent_name() -> str:
    """Who is asking, for the holder record: SECOND_BRAIN_AGENT, else a guess from the env."""
    explicit = os.environ.get("SECOND_BRAIN_AGENT")
    if explicit:
        return explicit
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude-code"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX"):
        return "codex"
    return "cli"


def _holder_path(store: Path) -> Path:
    return store / "write.lock.json"


def read_holder(store: str | os.PathLike[str]) -> dict[str, Any] | None:
    try:
        return json.loads(_holder_path(Path(store)).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextmanager
def write_lock(store: str | os.PathLike[str], *, blocking: bool = False,
               timeout: float = 600.0) -> Iterator[None]:
    """Hold the store's write lock for the duration of the block.

    ``blocking=False`` raises :class:`Busy` at once if another process holds it; ``blocking=True``
    waits up to ``timeout`` seconds (then raises Busy).
    """
    sp = Path(store)
    sp.mkdir(parents=True, exist_ok=True)
    fh = open(sp / "write.lock", "a+b")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                if _IS_WINDOWS:  # pragma: no cover
                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if not blocking or time.monotonic() >= deadline:
                    raise Busy(read_holder(sp)) from None
                time.sleep(0.2)
        try:
            _holder_path(sp).write_text(json.dumps({
                "pid": os.getpid(), "agent": agent_name(),
                "since": time.strftime("%Y-%m-%d %H:%M:%S")}), encoding="utf-8")
        except OSError:
            pass
        try:
            yield
        finally:
            try:
                _holder_path(sp).unlink()
            except OSError:
                pass
            if _IS_WINDOWS:  # pragma: no cover
                fh.seek(0)
                try:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:  # pragma: no cover
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


__all__ = ["Busy", "agent_name", "read_holder", "write_lock"]
