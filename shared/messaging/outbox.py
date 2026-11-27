"""Transactional Outbox helpers ensuring atomic DB mutation + reliable async event emission."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from shared.database.sqlite_base import open_sqlite, run_with_retry
from shared.messaging.event_bus import EventBus
from shared.messaging.events import DomainEvent


OUTBOX_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS outbox_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    event_type TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    producer TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished
    ON outbox_events(published_at, id);
"""


def enqueue_outbox_event(conn: sqlite3.Connection, topic: str, event: DomainEvent) -> None:
    """Inserts an event into the service's local DB outbox within the caller's open transaction."""
    conn.execute(
        """
        INSERT INTO outbox_events (
            event_id, topic, event_type, schema_version,
            producer, correlation_id, occurred_at, payload_json, published_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            event.event_id,
            topic,
            event.event_type,
            event.schema_version,
            event.producer,
            event.correlation_id,
            event.occurred_at,
            json.dumps(event.payload),
        ),
    )


class OutboxRelay:
    """Flushes committed outbox rows from a service's own DB to the Async Event Bus."""

    def __init__(self, service_db_path: Path, event_bus: EventBus) -> None:
        self.service_db_path = service_db_path
        self.event_bus = event_bus

    def flush_once(self) -> int:
        def _op() -> int:
            with open_sqlite(self.service_db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT id, event_id, topic, event_type, schema_version,
                           producer, correlation_id, occurred_at, payload_json
                    FROM outbox_events
                    WHERE published_at IS NULL
                    ORDER BY id ASC
                    LIMIT 50
                    """
                ).fetchall()
                if not rows:
                    return 0

                now_iso = datetime.now(timezone.utc).isoformat()
                for row in rows:
                    event = DomainEvent(
                        event_id=row["event_id"],
                        event_type=row["event_type"],
                        schema_version=row["schema_version"],
                        producer=row["producer"],
                        correlation_id=row["correlation_id"],
                        occurred_at=row["occurred_at"],
                        payload=json.loads(row["payload_json"]),
                    )
                    self.event_bus.publish(row["topic"], event)
                    conn.execute(
                        "UPDATE outbox_events SET published_at = ? WHERE id = ?",
                        (now_iso, row["id"]),
                    )
                return len(rows)

        return run_with_retry(_op)

    async def run_loop(self, stop_event: asyncio.Event, poll_interval_seconds: float = 0.15) -> None:
        while not stop_event.is_set():
            self.flush_once()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
            except asyncio.TimeoutError:
                pass
