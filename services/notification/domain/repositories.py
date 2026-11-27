"""Notification repository port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.notification.domain.models import Notification


class NotificationRepository(ABC):
    @abstractmethod
    def save(self, notification: Notification) -> None: ...

    @abstractmethod
    def list_for_user(self, user_id: str, limit: int = 30) -> list[Notification]: ...

    @abstractmethod
    def mark_read(self, notification_id: str, user_id: str) -> bool: ...

    @abstractmethod
    def mark_all_read(self, user_id: str) -> int: ...
