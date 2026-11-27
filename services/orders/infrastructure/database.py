"""Isolated SQLite database for Orders service ONLY (Database-per-Service)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from shared.database.sqlite_base import get_data_dir, open_sqlite
from shared.messaging.outbox import OUTBOX_SCHEMA_SQL


def get_orders_db_path() -> Path:
    return get_data_dir() / "orders.db"


def init_orders_db(db_path: Path | None = None) -> Path:
    target = db_path or get_orders_db_path()
    with open_sqlite(target) as conn:
        conn.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS orders (
                order_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                delivery_address TEXT NOT NULL,
                payment_method TEXT NOT NULL,
                status TEXT NOT NULL,
                payment_id TEXT,
                failure_reason TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS order_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                name TEXT NOT NULL,
                unit_label TEXT NOT NULL,
                unit_price_paise INTEGER NOT NULL,
                quantity INTEGER NOT NULL,
                image_emoji TEXT NOT NULL DEFAULT '🛒',
                FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            {OUTBOX_SCHEMA_SQL}
            """
        )
    return target


def connect_orders_db(db_path: Path | None = None) -> sqlite3.Connection:
    return open_sqlite(db_path or get_orders_db_path())
