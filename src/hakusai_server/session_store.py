"""
Session history persistence — SQLite-backed sessions & messages store.

Replaces the frontend's localStorage-only persistence (5–10 MB cap, no
cross-machine sync, lost on browser cache clear) with a server-side DB
that lives at ``~/.hakus/sessions.db``.

Why SQLite (and why in the sidecar, not Electron main):
  - The sidecar already owns every other piece of user data
    (``~/.hakus/config.yaml``, ``~/.hakus/recovery.db``,
    ``~/.hakus/user_states/``), so adding ``sessions.db`` there keeps
    all user data in one place — backup is "copy ~/.hakus".
  - sqlite3 is in the Python stdlib; no native rebuild dance like
    better-sqlite3 would impose on Electron upgrades.
  - The sidecar is the natural owner of session metadata because
    AgentCore's ContextManager (``hakus.agent``) already keys its
    in-memory cache by ``session_id`` — having the canonical
    session_id list server-side makes "list sessions" trivial.

Concurrency:
  - SQLite is opened with ``check_same_thread=False`` + a module-level
    ``threading.RLock``. FastAPI async endpoints call the sync functions
    directly — DB ops are sub-millisecond for our row counts (hundreds
    to low thousands), so blocking the event loop briefly is fine.
  - WAL mode is enabled for better read concurrency (so a slow
    ``GET /api/sessions`` doesn't block a concurrent write).

Schema versioning:
  - ``schema_version`` row in ``meta`` table. Future migrations add
    ``ALTER TABLE`` / ``CREATE INDEX`` blocks below the version check.
  - Current version: 1.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Where the DB file lives. Respects $HAKUS_HOME override (used by tests
# and by the Electron launcher when running portably).
_DEFAULT_HAKUS_HOME = os.path.expanduser("~/.hakus")


def _hakus_home() -> Path:
    env = os.environ.get("HAKUS_HOME")
    if env:
        return Path(env)
    return Path(_DEFAULT_HAKUS_HOME)


def _db_path() -> Path:
    return _hakus_home() / "sessions.db"


# Module-level connection + lock. We keep one connection for the lifetime
# of the sidecar process — sqlite3 handles concurrency via the lock + WAL.
_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


SCHEMA_VERSION = 1


def _schema_sql() -> str:
    return """
    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id                TEXT PRIMARY KEY,
        title             TEXT NOT NULL DEFAULT 'New Chat',
        remote_session_id TEXT,
        provider          TEXT,
        pinned            INTEGER NOT NULL DEFAULT 0,
        created_at        INTEGER NOT NULL,
        updated_at        INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS messages (
        id               TEXT PRIMARY KEY,
        session_id       TEXT NOT NULL,
        role             TEXT NOT NULL,
        content          TEXT NOT NULL DEFAULT '',
        reasoning        TEXT,
        tool_calls_json  TEXT,
        input_tokens     INTEGER,
        output_tokens    INTEGER,
        error            TEXT,
        streaming        INTEGER NOT NULL DEFAULT 0,
        created_at       INTEGER NOT NULL,
        updated_at       INTEGER NOT NULL,
        FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
    );

    CREATE INDEX IF NOT EXISTS idx_messages_session
        ON messages(session_id, created_at);
    CREATE INDEX IF NOT EXISTS idx_sessions_updated
        ON sessions(updated_at DESC);
    """


def _get_conn() -> sqlite3.Connection:
    """Lazily open the DB connection and run migrations if needed."""
    global _conn
    if _conn is not None:
        return _conn

    with _lock:
        if _conn is not None:
            return _conn

        db_path = _db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # check_same_thread=False because FastAPI's threadpool will call us.
        # We do our own locking via _lock.
        conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we wrap multi-step ops in BEGIN/COMMIT
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("PRAGMA synchronous=NORMAL;")  # WAL + NORMAL is safe & fast

        conn.executescript(_schema_sql())

        # Record schema version (idempotent — INSERT OR IGNORE)
        conn.execute(
            "INSERT OR IGNORE INTO meta(key, value) VALUES (?, ?)",
            ("schema_version", str(SCHEMA_VERSION)),
        )
        row = conn.execute(
            "SELECT value FROM meta WHERE key=?", ("schema_version",)
        ).fetchone()
        current = int(row["value"]) if row else 0

        if current < SCHEMA_VERSION:
            # Future: run migration blocks here.
            conn.execute(
                "UPDATE meta SET value=? WHERE key=?",
                (str(SCHEMA_VERSION), "schema_version"),
            )
            logger.info(
                f"session_store: migrated schema v{current} -> v{SCHEMA_VERSION}"
            )

        _conn = conn
        logger.info(f"session_store: opened {db_path}")
        return conn


# ============================================================================
# Sessions
# ============================================================================


def _row_to_session(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "remote_session_id": row["remote_session_id"],
        "provider": row["provider"],
        "pinned": bool(row["pinned"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_sessions() -> List[Dict[str, Any]]:
    """Return all sessions, newest first (by updated_at)."""
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY pinned DESC, updated_at DESC"
        ).fetchall()
    return [_row_to_session(r) for r in rows]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    conn = _get_conn()
    with _lock:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session_id,)
        ).fetchone()
    return _row_to_session(row) if row else None


def create_session(
    session_id: str,
    title: str = "New Chat",
    remote_session_id: Optional[str] = None,
    provider: Optional[str] = None,
    pinned: bool = False,
    created_at: Optional[int] = None,
    updated_at: Optional[int] = None,
) -> Dict[str, Any]:
    """Insert a new session row. Idempotent on id (raises if collision)."""
    import time as _time
    now = int(_time.time() * 1000)
    conn = _get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO sessions
                (id, title, remote_session_id, provider, pinned, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                title,
                remote_session_id,
                provider,
                1 if pinned else 0,
                created_at if created_at is not None else now,
                updated_at if updated_at is not None else now,
            ),
        )
    result = get_session(session_id)
    assert result is not None, "just inserted"
    return result


def update_session(
    session_id: str,
    *,
    title: Optional[str] = None,
    remote_session_id: Optional[str] = None,
    provider: Optional[str] = None,
    pinned: Optional[bool] = None,
    touch_updated: bool = True,
) -> Optional[Dict[str, Any]]:
    """Patch a session. Only non-None fields are updated."""
    sets: List[str] = []
    args: List[Any] = []
    if title is not None:
        sets.append("title=?")
        args.append(title)
    if remote_session_id is not None:
        sets.append("remote_session_id=?")
        args.append(remote_session_id)
    if provider is not None:
        sets.append("provider=?")
        args.append(provider)
    if pinned is not None:
        sets.append("pinned=?")
        args.append(1 if pinned else 0)
    if not sets and not touch_updated:
        return get_session(session_id)
    if touch_updated:
        import time as _time
        sets.append("updated_at=?")
        args.append(int(_time.time() * 1000))
    args.append(session_id)

    conn = _get_conn()
    with _lock:
        conn.execute(
            f"UPDATE sessions SET {', '.join(sets)} WHERE id=?", tuple(args)
        )
    return get_session(session_id)


def delete_session(session_id: str) -> bool:
    """Delete a session + cascade messages. Returns True if a row was deleted."""
    conn = _get_conn()
    with _lock:
        cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        return cur.rowcount > 0


# ============================================================================
# Messages
# ============================================================================


def _row_to_message(row: sqlite3.Row) -> Dict[str, Any]:
    tool_calls_raw = row["tool_calls_json"]
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "reasoning": row["reasoning"],
        "tool_calls": json.loads(tool_calls_raw) if tool_calls_raw else [],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "error": row["error"],
        "streaming": bool(row["streaming"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_messages(session_id: str) -> List[Dict[str, Any]]:
    conn = _get_conn()
    with _lock:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    return [_row_to_message(r) for r in rows]


def add_message(
    session_id: str,
    message_id: str,
    role: str,
    content: str = "",
    *,
    reasoning: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    error: Optional[str] = None,
    streaming: bool = False,
    created_at: Optional[int] = None,
    updated_at: Optional[int] = None,
) -> Dict[str, Any]:
    import time as _time
    now = int(_time.time() * 1000)
    conn = _get_conn()
    with _lock:
        conn.execute(
            """
            INSERT INTO messages
                (id, session_id, role, content, reasoning, tool_calls_json,
                 input_tokens, output_tokens, error, streaming,
                 created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                session_id,
                role,
                content,
                reasoning,
                json.dumps(tool_calls) if tool_calls else None,
                input_tokens,
                output_tokens,
                error,
                1 if streaming else 0,
                created_at if created_at is not None else now,
                updated_at if updated_at is not None else now,
            ),
        )
        # Bump session.updated_at so list_sessions ordering reflects new msg
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (updated_at if updated_at is not None else now, session_id),
        )
    # Re-read to return canonical row
    with _lock:
        row = conn.execute(
            "SELECT * FROM messages WHERE id=?", (message_id,)
        ).fetchone()
    return _row_to_message(row)


def update_message(
    message_id: str,
    *,
    content: Optional[str] = None,
    reasoning: Optional[str] = None,
    tool_calls: Optional[List[Dict[str, Any]]] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    error: Optional[str] = None,
    streaming: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    sets: List[str] = []
    args: List[Any] = []
    if content is not None:
        sets.append("content=?")
        args.append(content)
    if reasoning is not None:
        sets.append("reasoning=?")
        args.append(reasoning)
    if tool_calls is not None:
        sets.append("tool_calls_json=?")
        args.append(json.dumps(tool_calls))
    if input_tokens is not None:
        sets.append("input_tokens=?")
        args.append(input_tokens)
    if output_tokens is not None:
        sets.append("output_tokens=?")
        args.append(output_tokens)
    if error is not None:
        sets.append("error=?")
        args.append(error)
    if streaming is not None:
        sets.append("streaming=?")
        args.append(1 if streaming else 0)
    if not sets:
        return None

    import time as _time
    sets.append("updated_at=?")
    args.append(int(_time.time() * 1000))
    args.append(message_id)

    conn = _get_conn()
    with _lock:
        conn.execute(
            f"UPDATE messages SET {', '.join(sets)} WHERE id=?", tuple(args)
        )
        # Also bump session.updated_at (cheap; keeps list ordering fresh)
        sid_row = conn.execute(
            "SELECT session_id FROM messages WHERE id=?", (message_id,)
        ).fetchone()
        if sid_row:
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE id=?",
                (int(_time.time() * 1000), sid_row["session_id"]),
            )

    with _lock:
        row = conn.execute(
            "SELECT * FROM messages WHERE id=?", (message_id,)
        ).fetchone()
    return _row_to_message(row) if row else None


def delete_message(message_id: str) -> bool:
    conn = _get_conn()
    with _lock:
        cur = conn.execute("DELETE FROM messages WHERE id=?", (message_id,))
        return cur.rowcount > 0


def clear_session_messages(session_id: str) -> int:
    """Delete all messages belonging to a session, keep the session row.
    Returns number of messages deleted. Used by the TopBar 'clear conversation'
    button — user wants to start fresh in the same session without deleting it."""
    conn = _get_conn()
    import time as _time
    with _lock:
        cur = conn.execute(
            "DELETE FROM messages WHERE session_id=?", (session_id,)
        )
        n = cur.rowcount
        # Bump session.updated_at so it floats to the top of the sidebar
        conn.execute(
            "UPDATE sessions SET updated_at=? WHERE id=?",
            (int(_time.time() * 1000), session_id),
        )
    return n


# ============================================================================
# Bulk operations
# ============================================================================


def bulk_import(
    sessions: List[Dict[str, Any]],
    messages: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, int]:
    """Import sessions + messages (used by the migration endpoint).

    Idempotent: existing rows are replaced (INSERT OR REPLACE).
    Returns counts of inserted/replaced rows.
    """
    conn = _get_conn()
    n_sessions = 0
    n_messages = 0
    with _lock:
        conn.execute("BEGIN")
        try:
            for s in sessions:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO sessions
                        (id, title, remote_session_id, provider, pinned,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        s["id"],
                        s.get("title", "New Chat"),
                        s.get("remote_session_id"),
                        s.get("provider"),
                        1 if s.get("pinned") else 0,
                        s.get("created_at"),
                        s.get("updated_at"),
                    ),
                )
                n_sessions += 1
            for sid, msgs in messages.items():
                for m in msgs:
                    tc = m.get("tool_calls")
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO messages
                            (id, session_id, role, content, reasoning,
                             tool_calls_json, input_tokens, output_tokens,
                             error, streaming, created_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            m["id"],
                            sid,
                            m.get("role", "user"),
                            m.get("content", ""),
                            m.get("reasoning"),
                            json.dumps(tc) if tc else None,
                            m.get("input_tokens"),
                            m.get("output_tokens"),
                            m.get("error"),
                            1 if m.get("streaming") else 0,
                            m.get("created_at"),
                            m.get("updated_at"),
                        ),
                    )
                    n_messages += 1
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {"sessions": n_sessions, "messages": n_messages}


def wipe_all() -> int:
    """Delete ALL sessions + messages. Used by the dangerous reset button.
    Returns number of sessions deleted."""
    conn = _get_conn()
    with _lock:
        cur = conn.execute("SELECT COUNT(*) AS n FROM sessions").fetchone()
        n = cur["n"] if cur else 0
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
    return n


def export_all() -> Dict[str, Any]:
    """Export the entire sessions + messages DB as a JSON-serializable dict.

    Format:
        {
            "schema_version": 1,
            "exported_at": 1784384195428,
            "sessions": [...],
            "messages": { session_id: [messages], ... }
        }

    This is the inverse of bulk_import — the same payload shape can be
    POSTed back to /api/sessions/migrate to restore.
    """
    conn = _get_conn()
    with _lock:
        sess_rows = conn.execute(
            "SELECT * FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        msg_rows = conn.execute(
            "SELECT * FROM messages ORDER BY created_at ASC"
        ).fetchall()

    sessions = [_row_to_session(r) for r in sess_rows]
    messages: Dict[str, List[Dict[str, Any]]] = {}
    for r in msg_rows:
        m = _row_to_message(r)
        sid = m["session_id"]
        messages.setdefault(sid, []).append(m)

    import time as _time
    return {
        "schema_version": SCHEMA_VERSION,
        "exported_at": int(_time.time() * 1000),
        "sessions": sessions,
        "messages": messages,
    }
