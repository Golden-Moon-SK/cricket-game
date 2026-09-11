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
DB_PATH = PROJECT_ROOT / "users.db"
SCHEMA_PATH = PROJECT_ROOT / "schema.sql"
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
    with _connect() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


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


def recent_matches(user_id: int, limit: int = 8) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT runs, wickets, balls, fours, sixes, played_at
            FROM matches
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
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
