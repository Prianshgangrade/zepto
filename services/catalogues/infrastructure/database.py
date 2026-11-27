"""Isolated SQLite database for Catalogues service ONLY (Database-per-Service)."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from shared.database.sqlite_base import get_data_dir, open_sqlite


def get_catalogues_db_path() -> Path:
    return get_data_dir() / "catalogues.db"


def init_catalogues_db(db_path: Path | None = None) -> Path:
    target = db_path or get_catalogues_db_path()
    with open_sqlite(target) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS catalogue_items (
                product_id TEXT PRIMARY KEY,
                sku TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                unit_label TEXT NOT NULL,
                price_paise INTEGER NOT NULL,
                mrp_paise INTEGER NOT NULL,
                stock_qty INTEGER NOT NULL,
                eta_minutes INTEGER NOT NULL DEFAULT 10,
                image_emoji TEXT NOT NULL DEFAULT '🛒'
            );

            CREATE TABLE IF NOT EXISTS stock_reservations (
                order_id TEXT NOT NULL,
                product_id TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price_paise INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (order_id, product_id)
            );

            CREATE TABLE IF NOT EXISTS processed_events (
                event_id TEXT PRIMARY KEY,
                processed_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
    return target


def connect_catalogues_db(db_path: Path | None = None) -> sqlite3.Connection:
    return open_sqlite(db_path or get_catalogues_db_path())
