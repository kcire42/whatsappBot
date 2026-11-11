"""Persistencia mínima en SQLite: historial, deduplicación y modo humano.

Todo va separado por tenant_id, así un mismo cliente final que escribe a dos
negocios distintos nunca mezcla conversaciones.
"""
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    tenant_id TEXT, wa_user TEXT, role TEXT, content TEXT, ts REAL
);
CREATE INDEX IF NOT EXISTS idx_messages ON messages(tenant_id, wa_user, ts);
CREATE TABLE IF NOT EXISTS processed (message_id TEXT PRIMARY KEY, ts REAL);
CREATE TABLE IF NOT EXISTS handoff (
    tenant_id TEXT, wa_user TEXT, until_ts REAL, PRIMARY KEY (tenant_id, wa_user)
);
"""


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def mark_processed(self, message_id: str) -> bool:
        """True si es nuevo. Meta reintenta webhooks: esto evita responder dos veces."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO processed VALUES (?, ?)", (message_id, time.time())
            )
            return cur.rowcount == 1

    def add_message(self, tenant_id: str, wa_user: str, role: str, content: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO messages VALUES (?, ?, ?, ?, ?)",
                (tenant_id, wa_user, role, content, time.time()),
            )

    def history(self, tenant_id: str, wa_user: str, limit: int) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, content FROM messages WHERE tenant_id=? AND wa_user=? "
                "ORDER BY ts DESC LIMIT ?",
                (tenant_id, wa_user, limit),
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def set_handoff(self, tenant_id: str, wa_user: str, hours: float) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO handoff VALUES (?, ?, ?)",
                (tenant_id, wa_user, time.time() + hours * 3600),
            )

    def clear_handoff(self, tenant_id: str, wa_user: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM handoff WHERE tenant_id=? AND wa_user=?", (tenant_id, wa_user)
            )

    def in_handoff(self, tenant_id: str, wa_user: str) -> bool:
        with self._lock:
            row = self._db.execute(
                "SELECT until_ts FROM handoff WHERE tenant_id=? AND wa_user=?",
                (tenant_id, wa_user),
            ).fetchone()
        return bool(row and row[0] > time.time())
