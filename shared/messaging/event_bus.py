"""
Durable cross-process Async Event Bus (SQLite WAL topic log + consumer group offsets).
Supports:
- At-least-once delivery across separate OS microservice processes
- Independent consumer groups so every interested service receives fan-out events
- Cryptographic HMAC event verification (Zero-Trust messaging)
- Retry tracking and Dead Letter Queue (DLQ) for poison events
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from shared.database.sqlite_base import get_data_dir, open_sqlite, run_with_retry
from shared.messaging.events import DomainEvent
from shared.security.secrets import SecretsManager


logger = logging.getLogger(__name__)
EventHandler = Callable[[DomainEvent], Awaitable[None]]


class EventBus:
    """Persistent topic-based event bus transport isolated from service domain DBs."""

    def __init__(self, service_name: str, bus_db_path: Path | None = None) -> None:
        self.service_name = service_name
        self.db_path = Path(bus_db_path or (get_data_dir() / "event_bus.db"))
        self.secrets = SecretsManager(service_name)
        self._init_schema()

    def _connect(self):
        return open_sqlite(self.db_path)

    def _init_schema(self) -> None:
        def _op() -> None:
            with self._connect() as conn:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS bus_events (
                        seq INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE,
                        topic TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        schema_version TEXT NOT NULL,
                        producer TEXT NOT NULL,
                        correlation_id TEXT NOT NULL,
                        occurred_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL,
                        signature TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_bus_events_topic_seq
                        ON bus_events(topic, seq);

                    CREATE TABLE IF NOT EXISTS consumer_offsets (
                        consumer_group TEXT NOT NULL,
                        topic TEXT NOT NULL,
                        last_seq INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (consumer_group, topic)
                    );

                    CREATE TABLE IF NOT EXISTS dead_letter_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        consumer_group TEXT NOT NULL,
                        seq INTEGER NOT NULL,
                        event_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        error TEXT NOT NULL,
                        failed_at TEXT NOT NULL
                    );
                    """
                )

        run_with_retry(_op)

    def publish(self, topic: str, event: DomainEvent) -> DomainEvent:
        hmac_key = self.secrets.get_secret("event_bus_hmac_key")
        signed = event.sign(hmac_key)

        def _op() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO bus_events (
                        event_id, topic, event_type, schema_version,
                        producer, correlation_id, occurred_at, payload_json, signature
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        signed.event_id,
                        topic,
                        signed.event_type,
                        signed.schema_version,
                        signed.producer,
                        signed.correlation_id,
                        signed.occurred_at,
                        json.dumps(signed.payload),
                        signed.signature,
                    ),
                )

        run_with_retry(_op)
        return signed

    def _fetch_pending(self, consumer_group: str, topics: list[str]) -> list[tuple[int, str, DomainEvent]]:
        if not topics:
            return []

        def _op() -> list[tuple[int, str, DomainEvent]]:
            results: list[tuple[int, str, DomainEvent]] = []
            with self._connect() as conn:
                for topic in topics:
                    row = conn.execute(
                        "SELECT last_seq FROM consumer_offsets WHERE consumer_group = ? AND topic = ?",
                        (consumer_group, topic),
                    ).fetchone()
                    last_seq = int(row["last_seq"]) if row else 0
                    rows = conn.execute(
                        """
                        SELECT seq, topic, event_id, event_type, schema_version,
                               producer, correlation_id, occurred_at, payload_json, signature
                        FROM bus_events
                        WHERE topic = ? AND seq > ?
                        ORDER BY seq ASC
                        LIMIT 50
                        """,
                        (topic, last_seq),
                    ).fetchall()
                    for r in rows:
                        evt = DomainEvent(
                            event_id=r["event_id"],
                            event_type=r["event_type"],
                            schema_version=r["schema_version"],
                            producer=r["producer"],
                            correlation_id=r["correlation_id"],
                            occurred_at=r["occurred_at"],
                            payload=json.loads(r["payload_json"]),
                            signature=r["signature"],
                        )
                        results.append((int(r["seq"]), r["topic"], evt))
            return results

        return run_with_retry(_op)

    def _commit_offset(self, consumer_group: str, topic: str, seq: int) -> None:
        def _op() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO consumer_offsets (consumer_group, topic, last_seq)
                    VALUES (?, ?, ?)
                    ON CONFLICT(consumer_group, topic) DO UPDATE SET
                        last_seq = MAX(consumer_offsets.last_seq, excluded.last_seq)
                    """,
                    (consumer_group, topic, seq),
                )

        run_with_retry(_op)

    def _record_dlq(self, consumer_group: str, seq: int, event: DomainEvent, error: str) -> None:
        def _op() -> None:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO dead_letter_events (
                        consumer_group, seq, event_id, event_type, error, failed_at
                    ) VALUES (?, ?, ?, ?, ?, datetime('now'))
                    """,
                    (consumer_group, seq, event.event_id, event.event_type, error[:500]),
                )

        run_with_retry(_op)

    async def process_once(
        self,
        consumer_group: str,
        topic_handlers: dict[str, dict[str, EventHandler]],
        max_retries: int = 3,
    ) -> int:
        """
        Drains currently pending events for `consumer_group`.
        `topic_handlers` maps topic -> {event_type: async_handler}.
        Returns count of processed events.
        """
        hmac_key = self.secrets.get_secret("event_bus_hmac_key")
        topics = list(topic_handlers.keys())
        pending = self._fetch_pending(consumer_group, topics)
        processed = 0

        for seq, topic, event in pending:
            if not event.verify_signature(hmac_key):
                logger.error("Zero-Trust event signature verification failed for %s", event.event_id)
                self._record_dlq(consumer_group, seq, event, "Invalid HMAC event signature")
                self._commit_offset(consumer_group, topic, seq)
                continue

            handler = topic_handlers.get(topic, {}).get(event.event_type)
            if handler is None:
                self._commit_offset(consumer_group, topic, seq)
                continue

            succeeded = False
            last_error = ""
            for attempt in range(max_retries):
                try:
                    await handler(event)
                    succeeded = True
                    break
                except Exception as exc:  # pragma: no cover - defensive DLQ path
                    last_error = f"{type(exc).__name__}: {exc}"
                    logger.warning(
                        "Consumer %s failed on %s (attempt %d/%d): %s",
                        consumer_group,
                        event.event_id,
                        attempt + 1,
                        max_retries,
                        last_error,
                    )
                    await asyncio.sleep(0.05 * (attempt + 1))

            if not succeeded:
                self._record_dlq(consumer_group, seq, event, last_error)
            self._commit_offset(consumer_group, topic, seq)
            processed += 1

        return processed

    async def run_consumer_loop(
        self,
        consumer_group: str,
        topic_handlers: dict[str, dict[str, EventHandler]],
        stop_event: asyncio.Event,
        poll_interval_seconds: float = 0.15,
    ) -> None:
        while not stop_event.is_set():
            await self.process_once(consumer_group, topic_handlers)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_seconds)
            except asyncio.TimeoutError:
                pass
