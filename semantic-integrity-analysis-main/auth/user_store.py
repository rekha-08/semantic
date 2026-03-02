import hashlib
import os
import secrets
import sqlite3
from pathlib import Path
from typing import Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "users.db"


def _ensure_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                salt TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _hash_password(password: str, salt_hex: str) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return digest.hex()


def _normalize_username(username: str) -> str:
    return username.strip().lower()


def create_user(username: str, password: str) -> Tuple[bool, str]:
    _ensure_db()
    normalized = _normalize_username(username)

    if len(normalized) < 3:
        return False, "Username must be at least 3 characters."
    if len(password) < 8:
        return False, "Password must be at least 8 characters."

    salt_hex = secrets.token_hex(16)
    password_hash = _hash_password(password, salt_hex)

    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, salt) VALUES (?, ?, ?)",
            (normalized, password_hash, salt_hex),
        )
        conn.commit()
        return True, "Account created successfully."
    except sqlite3.IntegrityError:
        return False, "Username already exists."
    finally:
        conn.close()


def authenticate_user(username: str, password: str) -> Tuple[bool, str]:
    _ensure_db()
    normalized = _normalize_username(username)

    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT password_hash, salt FROM users WHERE username = ?",
            (normalized,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return False, "User not found."

    stored_hash, salt_hex = row
    candidate_hash = _hash_password(password, salt_hex)
    if candidate_hash != stored_hash:
        return False, "Incorrect password."
    return True, "Login successful."
