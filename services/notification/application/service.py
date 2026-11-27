"""Notification application use cases (data-driven event formatting)."""

from __future__ import annotations

import uuid

from services.notification.domain.models import Notification
from services.notification.domain.repositories import NotificationRepository
from shared.messaging.events import DomainEvent


def _format_inr(paise: int) -> str:
    return f"₹{paise / 100.0:.2f}"


# Table-driven mapping of domain events -> notification templates (uniform handling, zero duplication)
EVENT_TEMPLATES: dict[str, tuple[str, callable]] = {
    "OrderCreated": (
        "Order Placed",
        lambda p: f"Order {p.get('order_id')} placed for {_format_inr(int(p.get('total_paise', 0)))}. Processing payment.",
    ),
    "PaymentSucceeded": (
        "Payment Successful",
        lambda p: f"Payment of {_format_inr(int(p.get('amount_paise', 0)))} via {p.get('method', 'UPI')} succeeded for order {p.get('order_id')}.",
    ),
    "OrderConfirmed": (
        "Order Confirmed ⚡",
        lambda p: f"Order {p.get('order_id')} is confirmed! Your groceries are being packed for 10-min delivery.",
    ),
    "PaymentFailed": (
        "Payment Failed",
        lambda p: f"Payment failed for order {p.get('order_id')} ({p.get('failure_reason') or 'Declined'}). Reserved items were released.",
    ),
    "OrderCancelled": (
        "Order Cancelled",
        lambda p: f"Order {p.get('order_id')} was cancelled. Reserved stock has been released.",
    ),
    "PaymentRefunded": (
        "Refund Initiated",
        lambda p: f"Refund of {_format_inr(int(p.get('amount_paise', 0)))} initiated for cancelled order {p.get('order_id')}.",
    ),
}


class NotificationApplicationService:
    def __init__(self, repo: NotificationRepository) -> None:
        self.repo = repo

    def record_from_event(self, event: DomainEvent) -> Notification | None:
        template = EVENT_TEMPLATES.get(event.event_type)
        user_id = event.payload.get("user_id")
        if template is None or not user_id:
            return None

        title, message_builder = template
        notification = Notification(
            notification_id=f"ntf_{uuid.uuid4().hex[:10]}",
            user_id=str(user_id),
            order_id=str(event.payload.get("order_id", "")),
            event_type=event.event_type,
            channel="PUSH",
            title=title,
            message=message_builder(event.payload),
        )
        self.repo.save(notification)
        return notification

    def list_notifications(self, user_id: str) -> list[Notification]:
        return self.repo.list_for_user(user_id)

    def mark_read(self, notification_id: str, user_id: str) -> bool:
        return self.repo.mark_read(notification_id, user_id)

    def mark_all_read(self, user_id: str) -> int:
        return self.repo.mark_all_read(user_id)
