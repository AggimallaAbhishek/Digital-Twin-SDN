"""P4.4 audit ledger: every action's verdict, approval, application and outcome (decision P4.4-A).

SQLite (standard library) in one file, so the record survives restarts and the API (P3.6), the
loop (P4.5) and the evaluation (P6) read the same history. `actions` holds one row per action
with its current status; `events` is append-only: every status change, with its time and why.

Statuses: verified | rejected -> approved -> applied -> kept | rolled_back; failed (the set did
not apply and was undone); rollback_failed (needs an operator).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from common.schemas import ACTION_ADAPTER, Action, KPIValues, Verdict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS actions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    action_id TEXT UNIQUE NOT NULL,
    group_id TEXT NOT NULL,
    action TEXT NOT NULL,
    verdict TEXT NOT NULL,
    status TEXT NOT NULL,
    approved_by TEXT,
    previous TEXT,
    baseline TEXT,
    applied_at TEXT,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action_id TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ActionRecord:
    """One action as the ledger holds it now."""

    action_id: str
    group_id: str
    action: Action
    verdict: Verdict
    status: str
    approved_by: str | None
    previous: dict[str, Any] | None  # Any: whatever the actuator needs to revert
    baseline: KPIValues | None
    applied_at: datetime | None
    note: str


@dataclass(frozen=True)
class Event:
    """One status change."""

    ts: datetime
    action_id: str
    status: str
    note: str


class Ledger:
    """The executor's persistent record. One connection; callers serialise access."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

    def add(self, actions: Sequence[Action], verdicts: Sequence[Verdict], ts: datetime) -> None:
        """Store a verified set (one group, named after its first action)."""
        group = actions[0].action_id
        with self._db:
            for action, verdict in zip(actions, verdicts, strict=True):
                status = "verified" if verdict.accepted else "rejected"
                self._db.execute(
                    "INSERT INTO actions (action_id, group_id, action, verdict, status) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        action.action_id,
                        group,
                        action.model_dump_json(by_alias=True),
                        verdict.model_dump_json(),
                        status,
                    ),
                )
                self._event(ts, action.action_id, status, "; ".join(verdict.violations))

    def update(  # noqa: PLR0913 - one keyword per column the executor sets
        self,
        action_id: str,
        status: str,
        ts: datetime,
        note: str = "",
        *,
        approved_by: str | None = None,
        previous: dict[str, Any] | None = None,  # Any: the actuator's JSON config
        baseline: KPIValues | None = None,
        applied_at: datetime | None = None,
    ) -> None:
        """Change an action's status (and the columns given), and log the change."""
        with self._db:
            self._db.execute(
                "UPDATE actions SET status = ?, note = ?, "
                "approved_by = COALESCE(?, approved_by), previous = COALESCE(?, previous), "
                "baseline = COALESCE(?, baseline), applied_at = COALESCE(?, applied_at) "
                "WHERE action_id = ?",
                (
                    status,
                    note,
                    approved_by,
                    json.dumps(previous) if previous is not None else None,
                    baseline.model_dump_json() if baseline is not None else None,
                    applied_at.isoformat() if applied_at is not None else None,
                    action_id,
                ),
            )
            self._event(ts, action_id, status, note)

    def get(self, action_id: str) -> ActionRecord | None:
        row = self._db.execute("SELECT * FROM actions WHERE action_id = ?", (action_id,)).fetchone()
        return _record(row) if row is not None else None

    def group(self, group_id: str) -> list[ActionRecord]:
        rows = self._db.execute(
            "SELECT * FROM actions WHERE group_id = ? ORDER BY seq", (group_id,)
        ).fetchall()
        return [_record(r) for r in rows]

    def records(self, status: str | None = None) -> list[ActionRecord]:
        """Every action in the order it was verified, optionally only those in `status`."""
        rows = self._db.execute("SELECT * FROM actions ORDER BY seq").fetchall()
        return [r for r in map(_record, rows) if status is None or r.status == status]

    def applied_since(self, since: datetime) -> list[ActionRecord]:
        """Actions applied after `since` (whatever happened to them afterwards)."""
        return [r for r in self.records() if r.applied_at is not None and r.applied_at > since]

    def events(self, action_id: str) -> list[Event]:
        rows = self._db.execute(
            "SELECT * FROM events WHERE action_id = ? ORDER BY id", (action_id,)
        ).fetchall()
        return [
            Event(datetime.fromisoformat(r["ts"]), r["action_id"], r["status"], r["note"])
            for r in rows
        ]

    def _event(self, ts: datetime, action_id: str, status: str, note: str) -> None:
        self._db.execute(
            "INSERT INTO events (ts, action_id, status, note) VALUES (?, ?, ?, ?)",
            (ts.isoformat(), action_id, status, note),
        )


def _record(row: sqlite3.Row) -> ActionRecord:
    return ActionRecord(
        action_id=row["action_id"],
        group_id=row["group_id"],
        action=ACTION_ADAPTER.validate_json(row["action"]),
        verdict=Verdict.model_validate_json(row["verdict"]),
        status=row["status"],
        approved_by=row["approved_by"],
        previous=json.loads(row["previous"]) if row["previous"] else None,
        baseline=KPIValues.model_validate_json(row["baseline"]) if row["baseline"] else None,
        applied_at=datetime.fromisoformat(row["applied_at"]) if row["applied_at"] else None,
        note=row["note"],
    )
