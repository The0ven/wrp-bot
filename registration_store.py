"""SQLite persistence for nation registrations."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable

DRAFT = "draft"
AWAITING_STAFF = "awaiting_staff"
CHANGES_REQUESTED = "changes_requested"
REJECTED = "rejected"
WITHDRAWN = "withdrawn"
AWAITING_POPULATION = "awaiting_population"
PROVISIONING = "provisioning"
ACTIVE = "active"
RELEASED = "released"

LIVE_STATES = (DRAFT, AWAITING_STAFF, CHANGES_REQUESTED, AWAITING_POPULATION, PROVISIONING, ACTIVE)
EDITABLE_STATES = (DRAFT, CHANGES_REQUESTED)
WITHDRAWABLE_STATES = (DRAFT, AWAITING_STAFF, CHANGES_REQUESTED, AWAITING_POPULATION)

JSON_COLUMNS = ("draft", "submitted", "approved", "review", "amendment", "steps")
COLUMNS = (
    "id", "guild_id", "member_id", "source", "state", "revision", "step",
    "draft", "submitted", "approved", "review", "amendment", "steps", "notes",
    "population", "start_year", "population_by", "thread_id", "status_message_id",
    "dm_channel_id", "dm_message_id", "calendar_submission_id", "tracker_nation_id",
    "tracker_url", "temp_role_granted_at", "temp_role_expires_at", "temp_role_removed_at",
    "created_at", "updated_at", "wizard_message_id",
)
# Columns added after the first release; created on startup when missing.
ADDED_COLUMNS = {"wizard_message_id": "INTEGER"}

_live = ", ".join(f"'{s}'" for s in LIVE_STATES)
SCHEMA = f"""
CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    source TEXT NOT NULL DEFAULT 'signup',
    state TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    step TEXT NOT NULL DEFAULT 'identity',
    draft TEXT NOT NULL DEFAULT '{{}}',
    submitted TEXT,
    approved TEXT,
    review TEXT,
    amendment TEXT,
    steps TEXT NOT NULL DEFAULT '{{}}',
    notes TEXT,
    population INTEGER,
    start_year INTEGER,
    population_by INTEGER,
    thread_id INTEGER,
    status_message_id INTEGER,
    dm_channel_id INTEGER,
    dm_message_id INTEGER,
    calendar_submission_id TEXT,
    tracker_nation_id TEXT,
    tracker_url TEXT,
    temp_role_granted_at TEXT,
    temp_role_expires_at TEXT,
    temp_role_removed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    wizard_message_id INTEGER
);
CREATE UNIQUE INDEX IF NOT EXISTS applications_one_live
    ON applications (guild_id, member_id) WHERE state IN ({_live});
CREATE INDEX IF NOT EXISTS applications_state ON applications (state);
CREATE INDEX IF NOT EXISTS applications_calendar ON applications (calendar_submission_id);
CREATE TABLE IF NOT EXISTS files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id),
    purpose TEXT NOT NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT,
    size INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    actor_id INTEGER,
    kind TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).astimezone(timezone.utc).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class DuplicateApplication(Exception):
    """The member already has a live application in this guild."""


@dataclass
class Application:
    id: str
    guild_id: int
    member_id: int
    source: str
    state: str
    revision: int
    step: str
    draft: dict = field(default_factory=dict)
    submitted: dict | None = None
    approved: dict | None = None
    review: dict | None = None
    amendment: dict | None = None
    steps: dict = field(default_factory=dict)
    notes: str | None = None
    population: int | None = None
    start_year: int | None = None
    population_by: int | None = None
    thread_id: int | None = None
    status_message_id: int | None = None
    dm_channel_id: int | None = None
    dm_message_id: int | None = None
    calendar_submission_id: str | None = None
    tracker_nation_id: str | None = None
    tracker_url: str | None = None
    temp_role_granted_at: str | None = None
    temp_role_expires_at: str | None = None
    temp_role_removed_at: str | None = None
    created_at: str = ""
    updated_at: str = ""
    wizard_message_id: int | None = None

    @property
    def nation_name(self) -> str:
        data = self.approved or self.submitted or self.draft or {}
        return data.get("short_name") or data.get("official_name") or "Unnamed nation"

    def failed_steps(self) -> list[str]:
        return [name for name, info in self.steps.items() if info.get("status") == "failed"]


class RegistrationStore:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        existing = {row[1] for row in self._db.execute("PRAGMA table_info(applications)")}
        for column, kind in ADDED_COLUMNS.items():
            if column not in existing:
                self._db.execute(f"ALTER TABLE applications ADD COLUMN {column} {kind}")

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # Applications -----------------------------------------------------------

    def _row(self, row: sqlite3.Row | None) -> Application | None:
        if row is None:
            return None
        data = dict(row)
        for column in JSON_COLUMNS:
            raw = data.get(column)
            data[column] = json.loads(raw) if raw else ({} if column in ("draft", "steps") else None)
        return Application(**data)

    def create(self, guild_id: int, member_id: int, *, source: str = "signup",
               state: str = DRAFT, **fields: Any) -> Application:
        now = iso()
        values = {
            "id": uuid.uuid4().hex, "guild_id": guild_id, "member_id": member_id,
            "source": source, "state": state, "revision": 0, "step": "identity",
            "draft": {}, "steps": {}, "created_at": now, "updated_at": now, **fields,
        }
        encoded = {k: self._encode(k, v) for k, v in values.items()}
        columns = ", ".join(encoded)
        marks = ", ".join("?" for _ in encoded)
        with self._lock:
            try:
                self._db.execute(f"INSERT INTO applications ({columns}) VALUES ({marks})",
                                 tuple(encoded.values()))
            except sqlite3.IntegrityError as exc:
                raise DuplicateApplication(str(exc)) from exc
        return self.get(values["id"])

    @staticmethod
    def _encode(column: str, value: Any) -> Any:
        if column in JSON_COLUMNS:
            return None if value is None else json.dumps(value)
        return value

    def get(self, app_id: str) -> Application | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM applications WHERE id = ?", (app_id,)).fetchone()
        return self._row(row)

    def live_for_member(self, guild_id: int, member_id: int) -> Application | None:
        marks = ", ".join("?" for _ in LIVE_STATES)
        with self._lock:
            row = self._db.execute(
                f"SELECT * FROM applications WHERE guild_id = ? AND member_id = ? AND state IN ({marks})",
                (guild_id, member_id, *LIVE_STATES),
            ).fetchone()
        return self._row(row)

    def list_states(self, states: Iterable[str], guild_id: int | None = None) -> list[Application]:
        states = tuple(states)
        marks = ", ".join("?" for _ in states)
        sql = f"SELECT * FROM applications WHERE state IN ({marks})"
        params: list[Any] = list(states)
        if guild_id is not None:
            sql += " AND guild_id = ?"
            params.append(guild_id)
        with self._lock:
            rows = self._db.execute(sql + " ORDER BY updated_at", params).fetchall()
        return [self._row(r) for r in rows]

    def by_calendar_submission(self, submission_id: str) -> Application | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM applications WHERE calendar_submission_id = ?", (submission_id,)
            ).fetchone()
        return self._row(row)

    def update(self, app_id: str, *, expect_state: str | Iterable[str] | None = None,
               expect_revision: int | None = None, **fields: Any) -> bool:
        """Compare-and-set update. Returns False when the expectations no longer hold."""
        if "updated_at" not in fields:
            fields["updated_at"] = iso()
        unknown = set(fields) - set(COLUMNS)
        if unknown:
            raise ValueError(f"Unknown columns: {sorted(unknown)}")
        assignments = ", ".join(f"{k} = ?" for k in fields)
        params: list[Any] = [self._encode(k, v) for k, v in fields.items()]
        sql = f"UPDATE applications SET {assignments} WHERE id = ?"
        params.append(app_id)
        if expect_state is not None:
            states = (expect_state,) if isinstance(expect_state, str) else tuple(expect_state)
            sql += f" AND state IN ({', '.join('?' for _ in states)})"
            params.extend(states)
        if expect_revision is not None:
            sql += " AND revision = ?"
            params.append(expect_revision)
        with self._lock:
            try:
                cursor = self._db.execute(sql, params)
            except sqlite3.IntegrityError as exc:
                raise DuplicateApplication(str(exc)) from exc
            return cursor.rowcount == 1

    def set_step(self, app_id: str, step: str, status: str, detail: str | None = None) -> None:
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                row = self._db.execute("SELECT steps FROM applications WHERE id = ?", (app_id,)).fetchone()
                steps = json.loads(row["steps"]) if row and row["steps"] else {}
                steps[step] = {"status": status, "detail": detail, "at": iso()}
                self._db.execute("UPDATE applications SET steps = ?, updated_at = ? WHERE id = ?",
                                 (json.dumps(steps), iso(), app_id))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise

    def due_temp_roles(self, now: datetime | None = None) -> list[Application]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM applications WHERE temp_role_expires_at IS NOT NULL "
                "AND temp_role_removed_at IS NULL AND temp_role_expires_at <= ?",
                (iso(now),),
            ).fetchall()
        return [self._row(r) for r in rows]

    # Files ------------------------------------------------------------------

    def add_file(self, app_id: str, purpose: str, path: str, filename: str,
                 content_type: str | None, size: int) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO files (application_id, purpose, path, filename, content_type, size, uploaded_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (app_id, purpose, path, filename, content_type, size, iso()),
            )
            return int(cursor.lastrowid)

    def set_file_path(self, file_id: int, path: str) -> None:
        with self._lock:
            self._db.execute("UPDATE files SET path = ? WHERE id = ?", (path, file_id))

    def get_file(self, file_id: int | None) -> dict | None:
        if file_id is None:
            return None
        with self._lock:
            row = self._db.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
        return dict(row) if row else None

    # Events and settings ----------------------------------------------------

    def log(self, app_id: str, kind: str, actor_id: int | None = None, detail: Any = None) -> None:
        encoded = None if detail is None else json.dumps(detail, default=str)
        with self._lock:
            self._db.execute(
                "INSERT INTO events (application_id, actor_id, kind, detail, created_at) VALUES (?, ?, ?, ?, ?)",
                (app_id, actor_id, kind, encoded, iso()),
            )

    def events(self, app_id: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM events WHERE application_id = ? ORDER BY id", (app_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
