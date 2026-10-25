"""A run's activity log, for following work while it happens.

Each event is one JSON line in `EVENTS.jsonl` with a timestamp, a sequence
number, a kind and a message. A `start` event names a key, and the matching
`done` or `error` event closes it, so a reader can tell what is in flight and
for how long. The log is committed to the state Volume after every event, so
the API sees each one as soon as it is written.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

Emit = Callable[..., None]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Events:
    def __init__(self, path: Path, commit: Callable[[], None] | None = None) -> None:
        self.path = Path(path)
        self._commit = commit
        self._seq = len(read(self.path))

    def emit(self, kind: str, message: str, *, phase: str | None = None, key: str | None = None,
             **data: Any) -> None:
        self._seq += 1
        record = {"seq": self._seq, "at": _now(), "kind": kind, "message": message}
        if phase:
            record["phase"] = phase
        if key:
            record["key"] = key
        if data:
            record["data"] = data
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        if self._commit:
            self._commit()


def read(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def in_flight(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Start events not yet closed by a done or error event with the same key."""
    open_: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("key"):
            if event["kind"] == "start":
                open_[event["key"]] = event
            elif event["kind"] in ("done", "error"):
                open_.pop(event["key"], None)
    return list(open_.values())


def n(count: int, word: str, plural: str | None = None) -> str:
    """"1 paper", "3 papers"."""
    return f"{count} {word if count == 1 else (plural or word + 's')}"


def silent(*_args: Any, **_kwargs: Any) -> None:
    """An emit that records nothing, for callers without a log."""
