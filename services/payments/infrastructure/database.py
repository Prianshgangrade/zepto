"""Isolated SQLite database for Payments service ONLY (Database-per-Service)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from shared.database.sqlite_base import get_data_dir, open_sqlite
from shared.messaging.outbox import OUTBOX_SCHEMA_SQL


def get_payments_db_path() -> Path:
    return get_data_dir() / "payments.db"


def init_payments_db(db_path: Path | None = None) -> Path:
    target = db_path or get_payments_db_path()
    with open_sqlite(target) as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS payments (
                payment_id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                method TEXT NOT NULL,
                payment_token TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                status TEXT NOT NULL,
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_payments_order ON payments(order_id);

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            {OUTBOX_SCHEMA_SQL}
            """
        )
    return target


def connect_payments_db(db_path: Path | None = None) -> sqlite3.Connection:
    return open_sqlite(db_path or get_payments_db_path())
