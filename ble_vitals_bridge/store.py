"""One SQLite file for every device: local, no server, no ORM, no migrations to maintain.

The whole design rests on one column. ``dedupe_key`` is source + metric + moment + value, and it
is the primary key, so importing the same log twice, re-reading the same cuff frame, or running
tonight's pull over yesterday's file changes nothing. That is the property the previous
per-device scripts did not have: each wrote its own file and the same measurement could land
twice with two different timestamps.

Journal mode stays at SQLite's default (``delete``): these files live on a machine that can lose
power, and a WAL left behind by a killed process is a database nobody can open.
"""

from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    dedupe_key TEXT PRIMARY KEY,
    metric     TEXT NOT NULL,
    value      REAL NOT NULL,
    unit       TEXT NOT NULL,
    taken_at   TEXT NOT NULL,
    source     TEXT NOT NULL,
    device     TEXT NOT NULL DEFAULT '',
    group_id   TEXT NOT NULL DEFAULT '',
    raw        TEXT NOT NULL DEFAULT '{}',
    added_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS readings_metric_time ON readings(metric, taken_at DESC);
CREATE INDEX IF NOT EXISTS readings_source_time ON readings(source, taken_at DESC);
"""


def _moment(value: str) -> str:
    return value.replace("T", " ")[:19]


class Store:
    """The only place that knows SQL. Everything else deals in readings and rows."""

    def __init__(self, path):
        self.path = pathlib.Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self) -> None:
        self.conn.close()

    def add(self, readings) -> tuple[int, int]:
        """Insert whatever is new. Returns (inserted, already known)."""
        added = 0
        for reading in readings:
            row = reading.as_row()
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO readings "
                "(dedupe_key, metric, value, unit, taken_at, source, device, group_id, raw, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    row["dedupe_key"],
                    row["metric"],
                    row["value"],
                    row["unit"],
                    _moment(row["taken_at"]),
                    row["source"],
                    row["device"],
                    row["group_id"],
                    json.dumps(row["raw"], ensure_ascii=False, default=str),
                    datetime.now().replace(microsecond=0).isoformat(),
                ),
            )
            added += 1 if cursor.rowcount else 0
        self.conn.commit()
        return added, len(readings) - added

    def latest(self, metric: str | None = None, limit: int = 30) -> list:
        """The most recent reading per metric, newest first."""
        if metric:
            rows = self.conn.execute(
                "SELECT * FROM readings WHERE metric = ? ORDER BY taken_at DESC LIMIT ?", (metric, limit)
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM readings WHERE (metric, taken_at) IN "
                "(SELECT metric, MAX(taken_at) FROM readings GROUP BY metric) ORDER BY metric"
            )
        return [dict(row) for row in rows]

    def series(self, metric: str, days: int = 30) -> list:
        since = (datetime.now() - timedelta(days=days)).replace(microsecond=0).isoformat()
        rows = self.conn.execute(
            "SELECT taken_at, value, unit, source, group_id FROM readings "
            "WHERE metric = ? AND taken_at >= ? ORDER BY taken_at",
            (metric, _moment(since)),
        )
        return [dict(row) for row in rows]

    def sources(self) -> list:
        """When each source last wrote, in hours, so a stale device is a number and not a guess."""
        rows = self.conn.execute(
            "SELECT source, metric, COUNT(*) AS readings, MAX(taken_at) AS last FROM readings "
            "GROUP BY source, metric ORDER BY source, metric"
        )
        now = datetime.now()
        out = []
        for row in rows:
            item = dict(row)
            try:
                age = now - datetime.fromisoformat(item["last"])
                item["age_hours"] = round(age.total_seconds() / 3600, 1)
            except ValueError:
                item["age_hours"] = None
            out.append(item)
        return out

    def count(self, metric: str | None = None) -> int:
        if metric:
            row = self.conn.execute("SELECT COUNT(*) FROM readings WHERE metric = ?", (metric,)).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) FROM readings").fetchone()
        return int(row[0])
