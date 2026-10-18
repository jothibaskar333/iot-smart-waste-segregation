"""SQLite persistence layer.

A new connection is opened per operation, which keeps things thread-safe
for the Flask request threads and the background MQTT thread.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_readings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp      TEXT    NOT NULL,
    source         TEXT    NOT NULL,           -- 'simulator' or 'mqtt'
    device_id      TEXT,
    ir_detected    INTEGER NOT NULL,
    moisture       REAL    NOT NULL,
    metal_detected INTEGER NOT NULL,
    classification TEXT    NOT NULL            -- WET / DRY / METAL / NONE
);

CREATE TABLE IF NOT EXISTS sorting_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    reading_id   INTEGER NOT NULL REFERENCES sensor_readings(id),
    category     TEXT    NOT NULL,             -- WET / DRY / METAL
    servo_action TEXT    NOT NULL,
    servo_angle  INTEGER NOT NULL,
    source       TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS fill_level_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    wet       REAL NOT NULL,
    dry       REAL NOT NULL,
    metal     REAL NOT NULL,
    source    TEXT NOT NULL,                   -- 'simulator', 'mqtt', 'reset', 'init'
    simulated INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT    NOT NULL,
    bin         TEXT    NOT NULL,
    level       REAL    NOT NULL,
    threshold   REAL    NOT NULL,
    message     TEXT    NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    resolved_at TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON sorting_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON alerts(active);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Database:
    def __init__(self, path: str):
        self.path = path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # --- settings ----------------------------------------------------------
    def get_settings(self) -> dict[str, str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}

    def save_settings(self, values: dict) -> None:
        with self.connect() as conn:
            conn.executemany(
                "INSERT INTO settings(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [(k, str(v)) for k, v in values.items()],
            )

    # --- readings & events -------------------------------------------------
    def record_reading_and_event(
        self,
        reading: dict,
        classification: str,
        source: str,
        device_id: str | None,
        servo: dict | None,
        timestamp: str | None = None,
    ) -> dict:
        """Store a sensor reading and, if an item was sorted, its sorting event."""
        ts = timestamp or utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO sensor_readings(timestamp, source, device_id, ir_detected, "
                "moisture, metal_detected, classification) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    ts,
                    source,
                    device_id,
                    int(reading["ir_detected"]),
                    reading["moisture"],
                    int(reading["metal_detected"]),
                    classification,
                ),
            )
            reading_id = cur.lastrowid
            event_id = None
            if servo is not None:
                cur = conn.execute(
                    "INSERT INTO sorting_events(timestamp, reading_id, category, servo_action, "
                    "servo_angle, source) VALUES (?, ?, ?, ?, ?, ?)",
                    (ts, reading_id, classification, servo["action"], servo["target_angle"], source),
                )
                event_id = cur.lastrowid
        return {"reading_id": reading_id, "event_id": event_id, "timestamp": ts}

    def get_events(self, limit: int = 20) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT e.id, e.timestamp, e.category, e.servo_action, e.servo_angle, e.source, "
                "r.device_id, r.ir_detected, r.moisture, r.metal_detected "
                "FROM sorting_events e JOIN sensor_readings r ON r.id = e.reading_id "
                "ORDER BY e.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "ir_detected": bool(row["ir_detected"]),
                "metal_detected": bool(row["metal_detected"]),
            }
            for row in rows
        ]

    def get_latest_reading(self) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        data = dict(row)
        data["ir_detected"] = bool(data["ir_detected"])
        data["metal_detected"] = bool(data["metal_detected"])
        return data

    def get_category_counts(self) -> dict[str, int]:
        counts = {"WET": 0, "DRY": 0, "METAL": 0}
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT category, COUNT(*) AS n FROM sorting_events GROUP BY category"
            ).fetchall()
        for row in rows:
            counts[row["category"]] = row["n"]
        return counts

    def count_no_item_readings(self) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM sensor_readings WHERE classification = 'NONE'"
            ).fetchone()[0]

    # --- fill levels -------------------------------------------------------
    def record_fill_levels(self, levels: dict, source: str, simulated: bool = True) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO fill_level_history(timestamp, wet, dry, metal, source, simulated) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (utc_now(), levels["wet"], levels["dry"], levels["metal"], source, int(simulated)),
            )

    def get_latest_fill_levels(self) -> dict | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT wet, dry, metal FROM fill_level_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None

    def get_fill_history(self, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM (SELECT * FROM fill_level_history ORDER BY id DESC LIMIT ?) "
                "ORDER BY id ASC",
                (limit,),
            ).fetchall()
        return [{**dict(row), "simulated": bool(row["simulated"])} for row in rows]

    # --- alerts ------------------------------------------------------------
    def create_alert(self, bin_name: str, level: float, threshold: float, message: str) -> int:
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO alerts(timestamp, bin, level, threshold, message, active) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                (utc_now(), bin_name, level, threshold, message),
            )
            return cur.lastrowid

    def has_active_alert(self, bin_name: str) -> bool:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM alerts WHERE bin = ? AND active = 1 LIMIT 1", (bin_name,)
            ).fetchone()
        return row is not None

    def resolve_alerts(self, bin_name: str | None = None) -> int:
        with self.connect() as conn:
            if bin_name:
                cur = conn.execute(
                    "UPDATE alerts SET active = 0, resolved_at = ? WHERE active = 1 AND bin = ?",
                    (utc_now(), bin_name),
                )
            else:
                cur = conn.execute(
                    "UPDATE alerts SET active = 0, resolved_at = ? WHERE active = 1",
                    (utc_now(),),
                )
            return cur.rowcount

    def get_alerts(self, active_only: bool = False, limit: int = 50) -> list[dict]:
        query = "SELECT * FROM alerts"
        if active_only:
            query += " WHERE active = 1"
        query += " ORDER BY id DESC LIMIT ?"
        with self.connect() as conn:
            rows = conn.execute(query, (limit,)).fetchall()
        return [{**dict(row), "active": bool(row["active"])} for row in rows]
