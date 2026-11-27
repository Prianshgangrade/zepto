"""Isolated SQLite database for Cart service ONLY (Database-per-Service)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from shared.database.sqlite_base import get_data_dir, open_sqlite


def get_cart_db_path() -> Path:
    return get_data_dir() / "cart.db"


def init_cart_db(db_path: Path | None = None) -> Path:
    target = db_path or get_cart_db_path()
    with open_sqlite(target) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS carts (
                user_id TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS cart_items (
                user_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                name TEXT NOT NULL,
                unit_label TEXT NOT NULL,
                unit_price_paise INTEGER NOT NULL,
                image_emoji TEXT NOT NULL DEFAULT '🛒',
                quantity INTEGER NOT NULL,
                PRIMARY KEY (user_id, product_id),
                FOREIGN KEY (user_id) REFERENCES carts(user_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
    return target


def connect_cart_db(db_path: Path | None = None) -> sqlite3.Connection:
    return open_sqlite(db_path or get_cart_db_path())
