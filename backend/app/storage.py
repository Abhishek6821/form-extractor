"""Document / form store.

A tiny SQLite-backed JSON store (stdlib only) so the API is stateful across
restarts without needing PostgreSQL for local development.  Swap for
PostgreSQL by re-implementing the four methods.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from typing import Any, Optional


class Store:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or os.environ.get("FORM_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "store.db"))
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS kv (bucket TEXT, id TEXT, body TEXT, PRIMARY KEY (bucket, id))")
        self._conn.commit()

    def put(self, bucket: str, id_: str, obj: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO kv VALUES (?, ?, ?)", (bucket, id_, json.dumps(obj, ensure_ascii=False)))
            self._conn.commit()

    def get(self, bucket: str, id_: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute("SELECT body FROM kv WHERE bucket=? AND id=?", (bucket, id_)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, bucket: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT body FROM kv WHERE bucket=? ORDER BY rowid DESC", (bucket,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def delete(self, bucket: str, id_: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE bucket=? AND id=?", (bucket, id_))
            self._conn.commit()
