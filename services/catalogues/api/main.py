"""Catalogues FastAPI microservice entrypoint (Stateless, Zero-Trust, Database-per-Service)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from services.catalogues.api.v1 import create_v1_router
from services.catalogues.api.v2 import create_v2_router
from services.catalogues.application.service import CatalogueApplicationService
from services.catalogues.infrastructure.event_consumer import build_catalogue_event_handlers
from services.catalogues.infrastructure.sqlite_repo import SQLiteCatalogueRepository
from shared.messaging.event_bus import EventBus
from shared.security.zero_trust import build_zero_trust_dependencies
from shared.versioning.headers import APIVersioningMiddleware


def create_catalogues_app(
    db_path: Path | None = None,
    bus_db_path: Path | None = None,
    start_background_consumer: bool = True,
) -> FastAPI:
    repo = SQLiteCatalogueRepository(db_path=db_path)
    app_service = CatalogueApplicationService(repo)
    app_service.seed_defaults()

    event_bus = EventBus("catalogues", bus_db_path=bus_db_path)
    handlers = build_catalogue_event_handlers(app_service, repo)

    require_read_caller, _ = build_zero_trust_dependencies(
        service_name="catalogues",
        allowed_callers={"api-gateway", "cart", "orders"},
    )
    require_orders_caller, _ = build_zero_trust_dependencies(
        service_name="catalogues",
        allowed_callers={"orders"},
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        task = None
        if start_background_consumer:
            task = asyncio.create_task(
                event_bus.run_consumer_loop("catalogues-group", handlers, stop_event)
            )
        try:
            yield
        finally:
            stop_event.set()
            if task:
                await task

    app = FastAPI(title="Zepto Catalogues Service", version="2.0.0", lifespan=lifespan)
    app.state.catalogue_service = app_service
    app.state.catalogue_repo = repo
    app.state.event_bus = event_bus
    app.state.event_handlers = handlers
    app.add_middleware(APIVersioningMiddleware)

    def get_service() -> CatalogueApplicationService:
        return app_service

    app.include_router(create_v1_router(get_service, require_read_caller, require_orders_caller))
    app.include_router(create_v2_router(get_service, require_read_caller))

    @app.get("/health")
    def health() -> dict:
        return {"service": "catalogues", "status": "ok", "database": str(repo.db_path.name)}

    return app


app = create_catalogues_app()
