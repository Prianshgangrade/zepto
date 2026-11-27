"""Async Event Bus consumer for Payments (auto-refunds when an order is cancelled)."""

from __future__ import annotations

from services.payments.application.service import PaymentApplicationService
from services.payments.infrastructure.sqlite_repo import SQLitePaymentRepository
from shared.messaging.event_bus import EventHandler
from shared.messaging.events import DomainEvent


def build_payments_event_handlers(
    app_service: PaymentApplicationService,
    repo: SQLitePaymentRepository,
) -> dict[str, dict[str, EventHandler]]:
    async def handle_order_cancelled(event: DomainEvent) -> None:
        if not repo.mark_event_processed_if_new(event.event_id):
            return
        order_id = event.payload.get("order_id")
        if order_id:
            app_service.refund_for_cancelled_order(str(order_id))

    return {
        "orders.events": {
            "OrderCancelled": handle_order_cancelled,
        }
    }
