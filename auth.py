"""Local account auth with salted PBKDF2 hashes stored in SQLite."""

from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"

DEFAULT_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash BLOB NOT NULL,
    salt BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    runs INTEGER NOT NULL,
    wickets INTEGER NOT NULL,
    balls INTEGER NOT NULL,
    fours INTEGER NOT NULL,
    sixes INTEGER NOT NULL,
    played_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);
"""


def _resolve_db_path() -> Path:
    """Return a writable SQLite database path, falling back to ~/.8bit_cricket/ if needed."""
    local_db = PROJECT_ROOT / "users.db"
    try:
        if local_db.exists() and os.access(local_db, os.W_OK):
            return local_db
        if not local_db.exists() and os.access(PROJECT_ROOT, os.W_OK):
            return local_db
    except Exception:
        pass
    fallback_dir = Path.home() / ".8bit_cricket"
    fallback_dir.mkdir(parents=True, exist_ok=True)
    return fallback_dir / "users.db"


DB_PATH = _resolve_db_path()
PBKDF2_ROUNDS = 120_000
MIN_USERNAME = 3
MAX_USERNAME = 16
MIN_PASSWORD = 6


@dataclass
class User:
    id: int
    username: str
    created_at: str
    high_score: int
    matches_played: int


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    schema = (
        SCHEMA_PATH.read_text(encoding="utf-8")
        if SCHEMA_PATH.exists()
        else DEFAULT_SCHEMA
    )
    with _connect() as conn:
        conn.executescript(schema)


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS
    )


def validate_username(username: str) -> str | None:
    name = username.strip()
    if len(name) < MIN_USERNAME or len(name) > MAX_USERNAME:
        return f"USERNAME MUST BE {MIN_USERNAME}-{MAX_USERNAME} CHARS"
    if not all(ch.isalnum() or ch in "_-" for ch in name):
        return "ONLY LETTERS, NUMBERS, _ AND -"
    return None


def validate_password(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"PASSWORD MUST BE {MIN_PASSWORD}+ CHARS"
    return None


def signup(username: str, password: str) -> tuple[User | None, str]:
    err = validate_username(username) or validate_password(password)
    if err:
        return None, err

    salt = os.urandom(16)
    digest = _hash_password(password, salt)
    now = datetime.now(timezone.utc).isoformat()

    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
                (username.strip(), digest, salt, now),
            )
            user_id = int(cur.lastrowid)
    except sqlite3.IntegrityError:
        return None, "USERNAME ALREADY TAKEN"

    user = get_user_by_id(user_id)
    assert user is not None
    return user, "ACCOUNT CREATED"


def login(username: str, password: str) -> tuple[User | None, str]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, salt FROM users WHERE username = ? COLLATE NOCASE",
            (username.strip(),),
        ).fetchone()

    if row is None:
        return None, "NO ACCOUNT WITH THAT NAME"

    expected = bytes(row["password_hash"])
    salt = bytes(row["salt"])
    actual = _hash_password(password, salt)
    if not hmac.compare_digest(expected, actual):
        return None, "WRONG PASSWORD"

    user = get_user_by_id(int(row["id"]))
    assert user is not None
    return user, "WELCOME BACK"


def get_user_by_id(user_id: int) -> User | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return None
        stats = conn.execute(
            """
            SELECT COALESCE(MAX(runs), 0) AS high_score,
                   COUNT(*) AS matches_played
            FROM matches WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()

    return User(
        id=int(row["id"]),
        username=str(row["username"]),
        created_at=str(row["created_at"]),
        high_score=int(stats["high_score"]),
        matches_played=int(stats["matches_played"]),
    )


def local_usernames() -> list[str]:
    """List account names created in this local game database.

    Password hashes and salts are deliberately not selected, so account-picker
    callers only ever receive public usernames.
    """
    with _connect() as conn:
        rows = conn.execute(
            "SELECT username FROM users ORDER BY username COLLATE NOCASE"
        ).fetchall()
    return [str(row["username"]) for row in rows]


def save_match(
    user_id: int,
    runs: int,
    wickets: int,
    balls: int,
    fours: int,
    sixes: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO matches (user_id, runs, wickets, balls, fours, sixes, played_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, runs, wickets, balls, fours, sixes, now),
        )


def recent_matches(user_id: int, limit: int | None = None) -> list[dict]:
    """Return a player's completed innings, newest first.

    ``matches`` is the source of truth for the Records screen.  A limit remains
    available for callers that need a compact recent-history list, while the
    game can request the full scorecard history.
    """
    limit_clause = "" if limit is None else "LIMIT ?"
    params: tuple[int, ...] = (user_id,) if limit is None else (user_id, limit)
    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT runs, wickets, balls, fours, sixes, played_at
            FROM matches
            WHERE user_id = ?
            ORDER BY id DESC
            {limit_clause}
            """,
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def leaderboard(limit: int = 8) -> list[tuple[str, int]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT u.username, MAX(m.runs) AS best
            FROM matches m
            JOIN users u ON u.id = m.user_id
            GROUP BY u.id
            ORDER BY best DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [(str(r["username"]), int(r["best"])) for r in rows]
