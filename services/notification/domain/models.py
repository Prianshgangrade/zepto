"""Notification DDD domain model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Notification:
    notification_id: str
    user_id: str
    order_id: str
    event_type: str
    channel: str
    title: str
    message: str
    is_read: bool = False
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
