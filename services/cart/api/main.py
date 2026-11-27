"""Cart FastAPI microservice entrypoint (Stateless, Zero-Trust, Database-per-Service)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from services.cart.api.v1 import create_v1_router
from services.cart.application.service import CartApplicationService
from services.cart.infrastructure.catalogues_client import CataloguesClient
from services.cart.infrastructure.event_consumer import build_cart_event_handlers
from services.cart.infrastructure.sqlite_repo import SQLiteCartRepository
from shared.messaging.event_bus import EventBus
from shared.security.zero_trust import build_zero_trust_dependencies
from shared.versioning.headers import APIVersioningMiddleware


def create_cart_app(
    db_path: Path | None = None,
    bus_db_path: Path | None = None,
    catalogues_client: CataloguesClient | None = None,
    start_background_consumer: bool = True,
) -> FastAPI:
    repo = SQLiteCartRepository(db_path=db_path)
    cat_client = catalogues_client or CataloguesClient()
    app_service = CartApplicationService(repo, cat_client)

    event_bus = EventBus("cart", bus_db_path=bus_db_path)
    handlers = build_cart_event_handlers(repo)

    _, require_user = build_zero_trust_dependencies(
        service_name="cart",
        allowed_callers={"api-gateway", "orders"},
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        task = None
        if start_background_consumer:
            task = asyncio.create_task(
                event_bus.run_consumer_loop("cart-group", handlers, stop_event)
            )
        try:
            yield
        finally:
            stop_event.set()
            if task:
                await task

    app = FastAPI(title="Zepto Cart Service", version="1.0.0", lifespan=lifespan)
    app.state.cart_service = app_service
    app.state.cart_repo = repo
    app.state.catalogues_client = cat_client
    app.state.event_bus = event_bus
    app.state.event_handlers = handlers
    app.add_middleware(APIVersioningMiddleware)

    def get_service() -> CartApplicationService:
        return app_service

    app.include_router(create_v1_router(get_service, require_user))

    @app.get("/health")
    def health() -> dict:
        return {"service": "cart", "status": "ok", "database": str(repo.db_path.name)}

    return app


app = create_cart_app()
