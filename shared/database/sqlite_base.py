"""SQLite WAL connection helper for isolated per-service databases and bus transport."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Callable, TypeVar


PROJECT_ROOT = Path(__file__).resolve().parents[2]
T = TypeVar("T")


def get_data_dir() -> Path:
    data_dir = Path(os.environ.get("ZEPTO_DATA_DIR") or (PROJECT_ROOT / "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def open_sqlite(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=5000;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def run_with_retry(fn: Callable[[], T], retries: int = 5) -> T:
    """Retries transient SQLITE_BUSY lock contentions cleanly across processes."""
    for attempt in range(retries):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt + 1 >= retries:
                raise
            time.sleep(0.03 * (attempt + 1))
    raise RuntimeError("Unreachable")
