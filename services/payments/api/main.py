"""Payments FastAPI microservice entrypoint (Stateless, Zero-Trust, Database-per-Service)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from services.payments.api.v1 import create_v1_router
from services.payments.application.service import PaymentApplicationService
from services.payments.infrastructure.event_consumer import build_payments_event_handlers
from services.payments.infrastructure.sqlite_repo import SQLitePaymentRepository
from shared.messaging.event_bus import EventBus
from shared.messaging.outbox import OutboxRelay
from shared.security.zero_trust import build_zero_trust_dependencies
from shared.versioning.headers import APIVersioningMiddleware


def create_payments_app(
    db_path: Path | None = None,
    bus_db_path: Path | None = None,
    start_background_workers: bool = True,
) -> FastAPI:
    repo = SQLitePaymentRepository(db_path=db_path)
    event_bus = EventBus("payments", bus_db_path=bus_db_path)
    outbox_relay = OutboxRelay(repo.db_path, event_bus)
    app_service = PaymentApplicationService(repo, outbox_relay)
    handlers = build_payments_event_handlers(app_service, repo)

    _, require_user = build_zero_trust_dependencies(
        service_name="payments",
        allowed_callers={"api-gateway", "orders"},
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        tasks: list[asyncio.Task] = []
        if start_background_workers:
            tasks.append(asyncio.create_task(outbox_relay.run_loop(stop_event)))
            tasks.append(
                asyncio.create_task(
                    event_bus.run_consumer_loop("payments-group", handlers, stop_event)
                )
            )
        try:
            yield
        finally:
            stop_event.set()
            for t in tasks:
                await t

    app = FastAPI(title="Zepto Payments Service", version="1.0.0", lifespan=lifespan)
    app.state.payment_service = app_service
    app.state.payment_repo = repo
    app.state.outbox_relay = outbox_relay
    app.state.event_bus = event_bus
    app.state.event_handlers = handlers
    app.add_middleware(APIVersioningMiddleware)

    def get_service() -> PaymentApplicationService:
        return app_service

    app.include_router(create_v1_router(get_service, require_user))

    @app.get("/health")
    def health() -> dict:
        return {"service": "payments", "status": "ok", "database": str(repo.db_path.name)}

    return app


app = create_payments_app()
