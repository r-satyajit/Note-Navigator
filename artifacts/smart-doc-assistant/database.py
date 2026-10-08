from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


class DuplicateDocumentError(ValueError):
    """Raised when the same file is already attached to a Space."""


def get_database_path() -> Path:
    configured_path = os.environ.get("NOTES_NAVIGATOR_DB_PATH")
    if configured_path:
        return Path(configured_path).expanduser().resolve()
    return Path(__file__).resolve().parent / "data" / "notes_navigator.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 15000")
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    database_path = get_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database_path, timeout=15) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS Users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                created_at TEXT NOT NULL,
                last_login_at TEXT
            );

            CREATE TABLE IF NOT EXISTS Spaces (
                id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (id, user_id),
                FOREIGN KEY (user_id) REFERENCES Users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_spaces_user_updated
                ON Spaces(user_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS Chats (
                id TEXT NOT NULL PRIMARY KEY,
                user_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                title TEXT NOT NULL,
                history_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (space_id, user_id)
                    REFERENCES Spaces(id, user_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_chats_user_space_updated
                ON Chats(user_id, space_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS Documents (
                id TEXT NOT NULL PRIMARY KEY,
                user_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                file_name TEXT NOT NULL,
                object_path TEXT NOT NULL UNIQUE,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL CHECK (byte_size > 0),
                created_at TEXT NOT NULL,
                UNIQUE (user_id, space_id, sha256),
                FOREIGN KEY (space_id, user_id)
                    REFERENCES Spaces(id, user_id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_documents_user_space
                ON Documents(user_id, space_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS SpaceIndexes (
                user_id TEXT NOT NULL,
                space_id TEXT NOT NULL,
                object_path TEXT NOT NULL UNIQUE,
                chunk_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (user_id, space_id),
                FOREIGN KEY (space_id, user_id)
                    REFERENCES Spaces(id, user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS AuthAttempts (
                email_hash TEXT NOT NULL PRIMARY KEY,
                failed_count INTEGER NOT NULL DEFAULT 0,
                window_started_at REAL NOT NULL
            );
            """
        )


def create_user(email: str, password_salt: bytes, password_hash: bytes) -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    now = _utc_now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO Users (id, email, password_salt, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, email, password_salt, password_hash, now),
        )
    return {"id": user_id, "email": email, "created_at": now}


def create_account(
    email: str,
    password_salt: bytes,
    password_hash: bytes,
) -> dict[str, str]:
    user_id = str(uuid.uuid4())
    space_id = str(uuid.uuid4())
    chat_id = str(uuid.uuid4())
    now = _utc_now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO Users (id, email, password_salt, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, email, password_salt, password_hash, now),
        )
        connection.execute(
            """
            INSERT INTO Spaces (id, user_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (space_id, user_id, "My Study Space", now, now),
        )
        connection.execute(
            """
            INSERT INTO Chats
                (id, user_id, space_id, title, history_json, created_at, updated_at)
            VALUES (?, ?, ?, 'New conversation', '[]', ?, ?)
            """,
            (chat_id, user_id, space_id, now, now),
        )
    return {
        "id": user_id,
        "email": email,
        "space_id": space_id,
        "chat_id": chat_id,
    }


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT id, email, password_salt, password_hash, created_at, last_login_at
            FROM Users
            WHERE email = ?
            """,
            (email,),
        ).fetchone()
    return _row_dict(row)


def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            "SELECT id, email, created_at, last_login_at FROM Users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return _row_dict(row)


def touch_user_login(user_id: str) -> None:
    with _connection() as connection:
        connection.execute(
            "UPDATE Users SET last_login_at = ? WHERE id = ?",
            (_utc_now(), user_id),
        )


def email_rate_limit_key(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def is_login_rate_limited(email: str, *, window_seconds: int = 900, limit: int = 8) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    with _connection() as connection:
        row = connection.execute(
            "SELECT failed_count, window_started_at FROM AuthAttempts WHERE email_hash = ?",
            (email_rate_limit_key(email),),
        ).fetchone()
    if row is None:
        return False
    if now - float(row["window_started_at"]) >= window_seconds:
        return False
    return int(row["failed_count"]) >= limit


def record_login_failure(email: str, *, window_seconds: int = 900) -> None:
    now = datetime.now(timezone.utc).timestamp()
    key = email_rate_limit_key(email)
    with _connection() as connection:
        row = connection.execute(
            "SELECT failed_count, window_started_at FROM AuthAttempts WHERE email_hash = ?",
            (key,),
        ).fetchone()
        if row is None or now - float(row["window_started_at"]) >= window_seconds:
            connection.execute(
                """
                INSERT INTO AuthAttempts (email_hash, failed_count, window_started_at)
                VALUES (?, 1, ?)
                ON CONFLICT(email_hash) DO UPDATE SET
                    failed_count = 1,
                    window_started_at = excluded.window_started_at
                """,
                (key, now),
            )
        else:
            connection.execute(
                "UPDATE AuthAttempts SET failed_count = failed_count + 1 WHERE email_hash = ?",
                (key,),
            )


def clear_login_failures(email: str) -> None:
    with _connection() as connection:
        connection.execute(
            "DELETE FROM AuthAttempts WHERE email_hash = ?",
            (email_rate_limit_key(email),),
        )


def create_space(user_id: str, name: str) -> str:
    space_id = str(uuid.uuid4())
    now = _utc_now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO Spaces (id, user_id, name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (space_id, user_id, name.strip(), now, now),
        )
    return space_id


def list_spaces(user_id: str) -> list[dict[str, Any]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, name, created_at, updated_at
            FROM Spaces
            WHERE user_id = ?
            ORDER BY updated_at DESC, name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def get_space(user_id: str, space_id: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, name, created_at, updated_at
            FROM Spaces
            WHERE user_id = ? AND id = ?
            """,
            (user_id, space_id),
        ).fetchone()
    return _row_dict(row)


def rename_space(user_id: str, space_id: str, name: str) -> bool:
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE Spaces
            SET name = ?, updated_at = ?
            WHERE user_id = ? AND id = ?
            """,
            (name.strip(), _utc_now(), user_id, space_id),
        )
    return cursor.rowcount == 1


def get_space_object_paths(user_id: str, space_id: str) -> list[str]:
    with _connection() as connection:
        document_rows = connection.execute(
            """
            SELECT object_path FROM Documents
            WHERE user_id = ? AND space_id = ?
            """,
            (user_id, space_id),
        ).fetchall()
        index_row = connection.execute(
            """
            SELECT object_path FROM SpaceIndexes
            WHERE user_id = ? AND space_id = ?
            """,
            (user_id, space_id),
        ).fetchone()
    paths = [str(row["object_path"]) for row in document_rows]
    if index_row is not None:
        paths.append(str(index_row["object_path"]))
    return paths


def delete_space(user_id: str, space_id: str) -> bool:
    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM Spaces WHERE user_id = ? AND id = ?",
            (user_id, space_id),
        )
    return cursor.rowcount == 1


def create_chat(user_id: str, space_id: str, title: str = "New conversation") -> str:
    chat_id = str(uuid.uuid4())
    now = _utc_now()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO Chats (id, user_id, space_id, title, history_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, '[]', ?, ?)
            """,
            (chat_id, user_id, space_id, title.strip() or "New conversation", now, now),
        )
        connection.execute(
            "UPDATE Spaces SET updated_at = ? WHERE user_id = ? AND id = ?",
            (now, user_id, space_id),
        )
    return chat_id


def list_chats(user_id: str, space_id: str) -> list[dict[str, Any]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, space_id, title, history_json, created_at, updated_at
            FROM Chats
            WHERE user_id = ? AND space_id = ?
            ORDER BY updated_at DESC
            """,
            (user_id, space_id),
        ).fetchall()
    return [dict(row) for row in rows]


def get_chat(user_id: str, space_id: str, chat_id: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT id, user_id, space_id, title, history_json, created_at, updated_at
            FROM Chats
            WHERE user_id = ? AND space_id = ? AND id = ?
            """,
            (user_id, space_id, chat_id),
        ).fetchone()
    return _row_dict(row)


def save_chat(
    user_id: str,
    space_id: str,
    chat_id: str,
    title: str,
    messages: list[dict[str, Any]],
) -> bool:
    now = _utc_now()
    with _connection() as connection:
        cursor = connection.execute(
            """
            UPDATE Chats
            SET title = ?, history_json = ?, updated_at = ?
            WHERE user_id = ? AND space_id = ? AND id = ?
            """,
            (
                title.strip() or "New conversation",
                json.dumps(messages, ensure_ascii=False),
                now,
                user_id,
                space_id,
                chat_id,
            ),
        )
        if cursor.rowcount:
            connection.execute(
                "UPDATE Spaces SET updated_at = ? WHERE user_id = ? AND id = ?",
                (now, user_id, space_id),
            )
    return cursor.rowcount == 1


def delete_chat(user_id: str, space_id: str, chat_id: str) -> bool:
    with _connection() as connection:
        cursor = connection.execute(
            "DELETE FROM Chats WHERE user_id = ? AND space_id = ? AND id = ?",
            (user_id, space_id, chat_id),
        )
    return cursor.rowcount == 1


def list_documents(user_id: str, space_id: str) -> list[dict[str, Any]]:
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT id, user_id, space_id, file_name, object_path, sha256, byte_size, created_at
            FROM Documents
            WHERE user_id = ? AND space_id = ?
            ORDER BY created_at DESC, file_name COLLATE NOCASE
            """,
            (user_id, space_id),
        ).fetchall()
    return [dict(row) for row in rows]


def add_document(
    *,
    document_id: str,
    user_id: str,
    space_id: str,
    file_name: str,
    object_path: str,
    sha256: str,
    byte_size: int,
) -> None:
    try:
        with _connection() as connection:
            connection.execute(
                """
                INSERT INTO Documents
                    (id, user_id, space_id, file_name, object_path, sha256, byte_size, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    user_id,
                    space_id,
                    file_name,
                    object_path,
                    sha256,
                    byte_size,
                    _utc_now(),
                ),
            )
    except sqlite3.IntegrityError as error:
        if "UNIQUE constraint failed: Documents.user_id, Documents.space_id, Documents.sha256" in str(error):
            raise DuplicateDocumentError("This file is already in the Space.") from error
        raise


def delete_document(user_id: str, space_id: str, document_id: str) -> str | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT object_path FROM Documents
            WHERE user_id = ? AND space_id = ? AND id = ?
            """,
            (user_id, space_id, document_id),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "DELETE FROM Documents WHERE user_id = ? AND space_id = ? AND id = ?",
            (user_id, space_id, document_id),
        )
    return str(row["object_path"])


def get_space_index(user_id: str, space_id: str) -> dict[str, Any] | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT user_id, space_id, object_path, chunk_count, updated_at
            FROM SpaceIndexes
            WHERE user_id = ? AND space_id = ?
            """,
            (user_id, space_id),
        ).fetchone()
    return _row_dict(row)


def set_space_index(
    user_id: str,
    space_id: str,
    object_path: str,
    chunk_count: int,
) -> None:
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO SpaceIndexes (user_id, space_id, object_path, chunk_count, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id, space_id) DO UPDATE SET
                object_path = excluded.object_path,
                chunk_count = excluded.chunk_count,
                updated_at = excluded.updated_at
            """,
            (user_id, space_id, object_path, chunk_count, _utc_now()),
        )


def delete_space_index(user_id: str, space_id: str) -> str | None:
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT object_path FROM SpaceIndexes
            WHERE user_id = ? AND space_id = ?
            """,
            (user_id, space_id),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            "DELETE FROM SpaceIndexes WHERE user_id = ? AND space_id = ?",
            (user_id, space_id),
        )
    return str(row["object_path"])
