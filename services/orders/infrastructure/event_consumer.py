"""Async Event Bus consumer for Orders (Eventual Consistency convergence on Payment events)."""

from __future__ import annotations

from services.orders.domain.models import InvalidOrderTransitionError
from services.orders.infrastructure.sqlite_repo import SQLiteOrderRepository
from shared.messaging.event_bus import EventHandler
from shared.messaging.events import DomainEvent
from shared.messaging.outbox import OutboxRelay


def build_orders_event_handlers(
    repo: SQLiteOrderRepository,
    outbox_relay: OutboxRelay,
) -> dict[str, dict[str, EventHandler]]:
    async def handle_payment_succeeded(event: DomainEvent) -> None:
        if not repo.mark_event_processed_if_new(event.event_id):
            return
        order_id = str(event.payload.get("order_id", ""))
        payment_id = str(event.payload.get("payment_id", ""))
        order = repo.get_by_id(order_id)
        if order is None:
            return
        try:
            if order.confirm(payment_id):
                repo.update_with_outbox(order, event_type="OrderConfirmed")
                outbox_relay.flush_once()
        except InvalidOrderTransitionError:
            pass

    async def handle_payment_failed(event: DomainEvent) -> None:
        if not repo.mark_event_processed_if_new(event.event_id):
            return
        order_id = str(event.payload.get("order_id", ""))
        payment_id = event.payload.get("payment_id")
        reason = str(event.payload.get("failure_reason") or "Payment failed")
        order = repo.get_by_id(order_id)
        if order is None:
            return
        try:
            if order.mark_payment_failed(reason=reason, payment_id=payment_id):
                repo.update_with_outbox(order, event_type=None)
        except InvalidOrderTransitionError:
            pass

    return {
        "payments.events": {
            "PaymentSucceeded": handle_payment_succeeded,
            "PaymentFailed": handle_payment_failed,
        }
    }
