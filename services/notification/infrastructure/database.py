"""Isolated SQLite database for Notification service ONLY (Database-per-Service)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from shared.database.sqlite_base import get_data_dir, open_sqlite


def get_notification_db_path() -> Path:
    return get_data_dir() / "notification.db"


def init_notification_db(db_path: Path | None = None) -> Path:
    target = db_path or get_notification_db_path()
    with open_sqlite(target) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                order_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                channel TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                is_read INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notifications_user
                ON notifications(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
    return target


def connect_notification_db(db_path: Path | None = None) -> sqlite3.Connection:
    return open_sqlite(db_path or get_notification_db_path())
