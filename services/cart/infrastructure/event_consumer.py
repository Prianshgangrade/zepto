"""Async Event Bus consumer for Cart (clears cart on OrderCreated - Eventual Consistency)."""

from __future__ import annotations

from services.cart.infrastructure.sqlite_repo import SQLiteCartRepository
from shared.messaging.event_bus import EventHandler
from shared.messaging.events import DomainEvent


def build_cart_event_handlers(repo: SQLiteCartRepository) -> dict[str, dict[str, EventHandler]]:
    async def handle_order_created(event: DomainEvent) -> None:
        if not repo.mark_event_processed_if_new(event.event_id):
            return
        user_id = event.payload.get("user_id")
        if user_id:
            repo.clear_cart(str(user_id))

    return {
        "orders.events": {
            "OrderCreated": handle_order_created,
        }
    }
