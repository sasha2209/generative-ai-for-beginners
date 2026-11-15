"""Persistence: SQLite with encrypted health data, provenance, consent and audit.

Health data (profiles and raw ingested documents) is encrypted before it is
written. Metadata needed to operate the service (user IDs, consent scopes,
audit events) is stored in the clear so it can be queried and reviewed.
Swap SQLite for Postgres in production; the interface stays the same.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import HealthProfile
from .security import FieldCipher, hash_token, new_token

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    data BLOB NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ingest_events (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source_type TEXT NOT NULL,
    raw BLOB NOT NULL,
    summary TEXT NOT NULL,
    received_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS consents (
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope TEXT NOT NULL,
    granted_at TEXT,
    revoked_at TEXT,
    PRIMARY KEY (user_id, scope)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path: str | Path, cipher: FieldCipher):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._cipher = cipher
        self._lock = threading.RLock()

    def _query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        # One connection is shared across worker threads, so reads take the lock too.
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    # --- users -------------------------------------------------------------
    def create_user(self) -> tuple[str, str]:
        user_id, token = uuid.uuid4().hex, new_token()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO users (id, token_hash, created_at) VALUES (?, ?, ?)",
                (user_id, hash_token(token), _now()),
            )
        self.save_profile(HealthProfile(user_id=user_id))
        self.audit(user_id, "user", "account.created")
        return user_id, token

    def user_for_token(self, token: str) -> Optional[str]:
        rows = self._query("SELECT id FROM users WHERE token_hash = ?", (hash_token(token),))
        return rows[0]["id"] if rows else None

    @property
    def write_lock(self) -> threading.RLock:
        """Hold while doing read-modify-write on a profile so concurrent
        requests can't overwrite each other's changes (single-process only;
        use row versioning / SELECT ... FOR UPDATE with Postgres)."""
        return self._lock

    # --- profiles ----------------------------------------------------------
    def get_profile(self, user_id: str) -> HealthProfile:
        row = next(iter(self._query("SELECT data FROM profiles WHERE user_id = ?", (user_id,))), None)
        if not row:
            return HealthProfile(user_id=user_id)
        return HealthProfile.model_validate_json(self._cipher.decrypt(row["data"]))

    def save_profile(self, profile: HealthProfile) -> None:
        blob = self._cipher.encrypt(profile.model_dump_json())
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO profiles (user_id, data, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data, updated_at = excluded.updated_at",
                (profile.user_id, blob, _now()),
            )

    # --- provenance --------------------------------------------------------
    def record_ingest(self, user_id: str, source_type: str, raw: str, summary: dict) -> str:
        event_id = uuid.uuid4().hex
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO ingest_events (id, user_id, source_type, raw, summary, received_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (event_id, user_id, source_type, self._cipher.encrypt(raw), json.dumps(summary), _now()),
            )
        return event_id

    def list_ingests(self, user_id: str) -> list[dict]:
        rows = self._query("SELECT id, source_type, summary, received_at FROM ingest_events "
            "WHERE user_id = ? ORDER BY received_at", (user_id,))
        return [{"id": r["id"], "source_type": r["source_type"],
                 "summary": json.loads(r["summary"]), "received_at": r["received_at"]} for r in rows]

    # --- consent -----------------------------------------------------------
    def set_consent(self, user_id: str, scope: str, granted: bool) -> None:
        now = _now()
        with self._lock, self._conn:
            if granted:
                self._conn.execute(
                    "INSERT INTO consents (user_id, scope, granted_at, revoked_at) VALUES (?, ?, ?, NULL) "
                    "ON CONFLICT(user_id, scope) DO UPDATE SET granted_at = excluded.granted_at, revoked_at = NULL",
                    (user_id, scope, now),
                )
            else:
                self._conn.execute(
                    "UPDATE consents SET revoked_at = ? WHERE user_id = ? AND scope = ?",
                    (now, user_id, scope),
                )

    def consents(self, user_id: str) -> list[dict]:
        rows = self._query("SELECT scope, granted_at, revoked_at FROM consents WHERE user_id = ? ORDER BY scope", (user_id,))
        return [dict(r) | {"active": r["revoked_at"] is None} for r in rows]

    def has_consent(self, user_id: str, scope: str) -> bool:
        row = next(iter(self._query("SELECT 1 FROM consents WHERE user_id = ? AND scope = ? AND revoked_at IS NULL", (user_id, scope))), None)
        return row is not None

    def users_with_consent(self, scope: str) -> list[str]:
        rows = self._query("SELECT user_id FROM consents WHERE scope = ? AND revoked_at IS NULL", (scope,))
        return [r["user_id"] for r in rows]

    # --- audit -------------------------------------------------------------
    def audit(self, user_id: str, actor: str, action: str, detail: Optional[dict] = None) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_log (user_id, actor, action, detail, ts) VALUES (?, ?, ?, ?, ?)",
                (user_id, actor, action, json.dumps(detail or {}), _now()),
            )

    def audit_log(self, user_id: str) -> list[dict]:
        rows = self._query("SELECT actor, action, detail, ts FROM audit_log WHERE user_id = ? ORDER BY id", (user_id,))
        return [{"actor": r["actor"], "action": r["action"],
                 "detail": json.loads(r["detail"] or "{}"), "ts": r["ts"]} for r in rows]

    # --- deletion ----------------------------------------------------------
    def delete_user(self, user_id: str) -> None:
        """Erase all health data and credentials. The audit trail is retained
        (it contains no health data) as evidence the deletion happened."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        self.audit(user_id, "user", "account.deleted")
