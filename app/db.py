"""SQLite store. mandos' own tables are below; a job pack adds its tables with pack.SCHEMA."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

import config

SCHEMA = """
-- Owner-approved prompt additions (the suggestions page). The prompt a job uses = prompts/<target>.txt + these blocks in id order.
CREATE TABLE IF NOT EXISTS prompt_additions (id INTEGER PRIMARY KEY, target TEXT, block TEXT, suggestion_id INTEGER, createdAt TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, set_at TEXT);
CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT UNIQUE, pw_hash TEXT, createdAt TEXT);
CREATE TABLE IF NOT EXISTS api_tokens (id INTEGER PRIMARY KEY, name TEXT, token_hash TEXT UNIQUE, last_used TEXT, createdAt TEXT);
CREATE TABLE IF NOT EXISTS job_runs (id INTEGER PRIMARY KEY, job TEXT, started TEXT, finished TEXT, status TEXT, detail TEXT, log TEXT, createdAt TEXT);
"""

TABLES = ["prompt_additions", "settings", "users", "api_tokens", "job_runs"]

_lock = threading.Lock()
_path = None


def init(path=None):
    global _path
    _path = path or config.DB_PATH
    if _path != ":memory:":
        os.makedirs(os.path.dirname(_path) or ".", exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)


_mem = None


def conn():
    global _mem
    if _path == ":memory:":
        if _mem is None:
            _mem = sqlite3.connect(":memory:", check_same_thread=False)
            _mem.row_factory = sqlite3.Row
        return _Shared(_mem)
    c = sqlite3.connect(_path, timeout=30)
    c.row_factory = sqlite3.Row
    return c


class _Shared:
    """Context manager around the single in-memory connection used by tests."""
    def __init__(self, c): self.c = c
    def __enter__(self): return self.c
    def __exit__(self, *a): self.c.commit()
    def __getattr__(self, n): return getattr(self.c, n)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def insert(table, row):
    row = {k: (json.dumps(v) if isinstance(v, (list, dict)) else v) for k, v in row.items()}
    row.setdefault("createdAt", now_iso())
    cols = ",".join(row)
    with _lock, conn() as c:
        cur = c.execute(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?' * len(row))})", list(row.values()))
        return cur.lastrowid


def update(table, id_, fields):
    if not fields:
        return
    with _lock, conn() as c:
        c.execute(f"UPDATE {table} SET {','.join(k + '=?' for k in fields)} WHERE id=?", [*fields.values(), id_])


def rows(table, where="", args=(), order="id DESC", limit=None):
    """Newest first by default."""
    q = f"SELECT * FROM {table}" + (f" WHERE {where}" if where else "") + f" ORDER BY {order}" + (f" LIMIT {int(limit)}" if limit else "")
    with conn() as c:
        return [dict(r) for r in c.execute(q, args)]


def get(table, id_):
    r = rows(table, "id=?", (id_,), limit=1)
    return r[0] if r else None
