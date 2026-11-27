"""Async Event Bus consumer for Catalogues (Saga compensation on PaymentFailed / OrderCancelled)."""

from __future__ import annotations

from services.catalogues.application.service import CatalogueApplicationService
from services.catalogues.infrastructure.sqlite_repo import SQLiteCatalogueRepository
from shared.messaging.event_bus import EventHandler
from shared.messaging.events import DomainEvent


def build_catalogue_event_handlers(
    app_service: CatalogueApplicationService,
    repo: SQLiteCatalogueRepository,
) -> dict[str, dict[str, EventHandler]]:
    async def handle_release_stock(event: DomainEvent) -> None:
        if not repo.mark_event_processed_if_new(event.event_id):
            return
        order_id = event.payload.get("order_id")
        if order_id:
            app_service.release_stock(str(order_id))

    return {
        "payments.events": {
            "PaymentFailed": handle_release_stock,
        },
        "orders.events": {
            "OrderCancelled": handle_release_stock,
        },
    }
