"""Notification FastAPI microservice entrypoint (Stateless, Zero-Trust, Database-per-Service)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from services.notification.api.v1 import create_v1_router
from services.notification.application.service import NotificationApplicationService
from services.notification.infrastructure.event_consumer import build_notification_event_handlers
from services.notification.infrastructure.sqlite_repo import SQLiteNotificationRepository
from shared.messaging.event_bus import EventBus
from shared.security.zero_trust import build_zero_trust_dependencies
from shared.versioning.headers import APIVersioningMiddleware


def create_notification_app(
    db_path: Path | None = None,
    bus_db_path: Path | None = None,
    start_background_consumer: bool = True,
) -> FastAPI:
    repo = SQLiteNotificationRepository(db_path=db_path)
    app_service = NotificationApplicationService(repo)
    event_bus = EventBus("notification", bus_db_path=bus_db_path)
    handlers = build_notification_event_handlers(app_service, repo)

    _, require_user = build_zero_trust_dependencies(
        service_name="notification",
        allowed_callers={"api-gateway"},
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        task = None
        if start_background_consumer:
            task = asyncio.create_task(
                event_bus.run_consumer_loop("notification-group", handlers, stop_event)
            )
        try:
            yield
        finally:
            stop_event.set()
            if task:
                await task

    app = FastAPI(title="Zepto Notification Service", version="1.0.0", lifespan=lifespan)
    app.state.notification_service = app_service
    app.state.notification_repo = repo
    app.state.event_bus = event_bus
    app.state.event_handlers = handlers
    app.add_middleware(APIVersioningMiddleware)

    def get_service() -> NotificationApplicationService:
        return app_service

    app.include_router(create_v1_router(get_service, require_user))

    @app.get("/health")
    def health() -> dict:
        return {"service": "notification", "status": "ok", "database": str(repo.db_path.name)}

    return app


app = create_notification_app()
