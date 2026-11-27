"""Orders FastAPI microservice entrypoint (Stateless, Zero-Trust, Database-per-Service)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from services.orders.api.v1 import create_v1_router
from services.orders.application.service import OrderApplicationService
from services.orders.infrastructure.clients import OrdersServiceClients
from services.orders.infrastructure.event_consumer import build_orders_event_handlers
from services.orders.infrastructure.sqlite_repo import SQLiteOrderRepository
from shared.messaging.event_bus import EventBus
from shared.messaging.outbox import OutboxRelay
from shared.security.zero_trust import build_zero_trust_dependencies
from shared.versioning.headers import APIVersioningMiddleware


def create_orders_app(
    db_path: Path | None = None,
    bus_db_path: Path | None = None,
    clients: OrdersServiceClients | None = None,
    start_background_workers: bool = True,
) -> FastAPI:
    repo = SQLiteOrderRepository(db_path=db_path)
    svc_clients = clients or OrdersServiceClients()
    event_bus = EventBus("orders", bus_db_path=bus_db_path)
    outbox_relay = OutboxRelay(repo.db_path, event_bus)
    app_service = OrderApplicationService(repo, svc_clients, outbox_relay)
    handlers = build_orders_event_handlers(repo, outbox_relay)

    _, require_user = build_zero_trust_dependencies(
        service_name="orders",
        allowed_callers={"api-gateway"},
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if start_background_workers:
            tasks.append(asyncio.create_task(outbox_relay.run_loop(stop_event)))
            tasks.append(
                asyncio.create_task(
                    event_bus.run_consumer_loop("orders-group", handlers, stop_event)
                )
            )
        try:
            yield
        finally:
            stop_event.set()
            for t in tasks:
                await t

    app = FastAPI(title="Zepto Orders Service", version="1.0.0", lifespan=lifespan)
    app.state.order_service = app_service
    app.state.order_repo = repo
    app.state.clients = svc_clients
    app.state.outbox_relay = outbox_relay
    app.state.event_bus = event_bus
    app.state.event_handlers = handlers
    app.add_middleware(APIVersioningMiddleware)

    def get_service() -> OrderApplicationService:
        return app_service

    app.include_router(create_v1_router(get_service, require_user))

    @app.get("/health")
    def health() -> dict:
        return {"service": "orders", "status": "ok", "database": str(repo.db_path.name)}

    return app


app = create_orders_app()
