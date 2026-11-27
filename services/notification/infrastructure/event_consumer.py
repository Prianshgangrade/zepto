"""Async Event Bus consumer for Notification (completely decoupled from Orders/Payments)."""

from __future__ import annotations

from services.notification.application.service import (
    EVENT_TEMPLATES,
    NotificationApplicationService,
)
from services.notification.infrastructure.sqlite_repo import SQLiteNotificationRepository
from shared.messaging.event_bus import EventHandler
from shared.messaging.events import DomainEvent


def build_notification_event_handlers(
    app_service: NotificationApplicationService,
    repo: SQLiteNotificationRepository,
) -> dict[str, dict[str, EventHandler]]:
    async def handle_event(event: DomainEvent) -> None:
        if not repo.mark_event_processed_if_new(event.event_id):
            return
        app_service.record_from_event(event)

    return {
        "orders.events": {
            evt: handle_event for evt in ("OrderCreated", "OrderConfirmed", "OrderCancelled")
            if evt in EVENT_TEMPLATES
        },
        "payments.events": {
            evt: handle_event for evt in ("PaymentSucceeded", "PaymentFailed", "PaymentRefunded")
            if evt in EVENT_TEMPLATES
        },
    }
