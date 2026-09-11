"""The previous run, on disk.

This is what makes the diff real rather than simulated: run N writes a file,
run N+1 reads it back and compares. Delete the file and the next run is a
baseline again.

The write is atomic (temp file then ``os.replace``) because a scheduled job
that is killed mid-write should leave the last good snapshot behind, not a
truncated one that breaks every future run.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import Snapshot


class StateError(RuntimeError):
    pass


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path: str | Path) -> Snapshot | None:
    """The previous snapshot, or None if there is not one yet."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StateError(
            f"{path} is not readable as JSON ({exc}). Delete it to start a new "
            f"baseline, or restore it from backup."
        ) from None
    if data.get("version") != 1:
        raise StateError(
            f"{path} was written by a different version of this tool "
            f"(version {data.get('version')!r}); delete it to start a new baseline."
        )
    return Snapshot.from_json(data)


def save(path: str | Path, snapshot: Snapshot) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp{os.getpid()}")
    temp.write_text(
        json.dumps(snapshot.to_json(), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temp, path)
