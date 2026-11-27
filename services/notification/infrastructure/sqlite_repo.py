"""SQLite repository implementation for Notification."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from services.notification.domain.models import Notification
from services.notification.domain.repositories import NotificationRepository
from services.notification.infrastructure.database import connect_notification_db, init_notification_db
from shared.database.sqlite_base import run_with_retry


class SQLiteNotificationRepository(NotificationRepository):
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = init_notification_db(db_path)

    @staticmethod
    def _row_to_entity(row: sqlite3.Row) -> Notification:
        return Notification(
            notification_id=row["notification_id"],
            user_id=row["user_id"],
            order_id=row["order_id"],
            event_type=row["event_type"],
            channel=row["channel"],
            title=row["title"],
            message=row["message"],
            is_read=bool(row["is_read"]),
            created_at=row["created_at"],
        )

    def save(self, notification: Notification) -> None:
        def _op() -> None:
            with connect_notification_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO notifications (
                        notification_id, user_id, order_id, event_type,
                        channel, title, message, is_read, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        notification.notification_id,
                        notification.user_id,
                        notification.order_id,
                        notification.event_type,
                        notification.channel,
                        notification.title,
                        notification.message,
                        1 if notification.is_read else 0,
                        notification.created_at,
                    ),
                )

        run_with_retry(_op)

    def list_for_user(self, user_id: str, limit: int = 30) -> list[Notification]:
        def _op() -> list[Notification]:
            with connect_notification_db(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM notifications
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, limit),
                ).fetchall()
                return [self._row_to_entity(r) for r in rows]

        return run_with_retry(_op)

    def mark_read(self, notification_id: str, user_id: str) -> bool:
        def _op() -> bool:
            with connect_notification_db(self.db_path) as conn:
                cursor = conn.execute(
                    "UPDATE notifications SET is_read = 1 WHERE notification_id = ? AND user_id = ?",
                    (notification_id, user_id),
                )
                return cursor.rowcount > 0

        return run_with_retry(_op)

    def mark_all_read(self, user_id: str) -> int:
        def _op() -> int:
            with connect_notification_db(self.db_path) as conn:
                cursor = conn.execute(
                    "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
                    (user_id,),
                )
                return cursor.rowcount

        return run_with_retry(_op)

    def mark_event_processed_if_new(self, event_id: str) -> bool:
        def _op() -> bool:
            with connect_notification_db(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO processed_events (event_id) VALUES (?)",
                    (event_id,),
                )
                return cursor.rowcount == 1

        return run_with_retry(_op)
