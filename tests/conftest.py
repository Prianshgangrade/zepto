"""Shared pytest fixtures spinning up all isolated microservices in-process via ASGITransport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.api_gateway.main import create_api_gateway_app
from services.cart.api.main import create_cart_app
from services.cart.infrastructure.catalogues_client import CataloguesClient as CartCataloguesClient
from services.catalogues.api.main import create_catalogues_app
from services.notification.api.main import create_notification_app
from services.orders.api.main import create_orders_app
from services.orders.infrastructure.clients import OrdersServiceClients
from services.payments.api.main import create_payments_app
from shared.security.secrets import SecretsManager


@dataclass
class ZeptoTestMesh:
    data_dir: Path
    vault_path: Path
    catalogues_app: object
    cart_app: object
    payments_app: object
    orders_app: object
    notification_app: object
    gateway_app: object

    async def flush_async_events(self, rounds: int = 3) -> None:
        """Flushes outboxes and processes all consumer groups for deterministic eventual consistency."""
        for _ in range(rounds):
            self.orders_app.state.outbox_relay.flush_once()
            self.payments_app.state.outbox_relay.flush_once()
            await self.cart_app.state.event_bus.process_once(
                "cart-group", self.cart_app.state.event_handlers
            )
            await self.orders_app.state.event_bus.process_once(
                "orders-group", self.orders_app.state.event_handlers
            )
            await self.catalogues_app.state.event_bus.process_once(
                "catalogues-group", self.catalogues_app.state.event_handlers
            )
            await self.payments_app.state.event_bus.process_once(
                "payments-group", self.payments_app.state.event_handlers
            )
            await self.notification_app.state.event_bus.process_once(
                "notification-group", self.notification_app.state.event_handlers
            )

    def gateway_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.gateway_app),
            base_url="http://gateway.test",
        )


def build_test_mesh(tmp_path: Path, monkeypatch, *, timeout_seconds: float = 1.5) -> ZeptoTestMesh:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    vault_path = tmp_path / ".secrets" / "vault.json"

    monkeypatch.setenv("ZEPTO_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ZEPTO_SECRETS_PATH", str(vault_path))
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", str(timeout_seconds))
    SecretsManager.ensure_vault(vault_path)

    bus_db = data_dir / "event_bus.db"

    catalogues_app = create_catalogues_app(
        db_path=data_dir / "catalogues.db",
        bus_db_path=bus_db,
        start_background_consumer=False,
    )
    cart_app = create_cart_app(
        db_path=data_dir / "cart.db",
        bus_db_path=bus_db,
        catalogues_client=CartCataloguesClient(
            base_url="http://catalogues.test",
            transport=httpx.ASGITransport(app=catalogues_app),
            timeout_seconds=timeout_seconds,
        ),
        start_background_consumer=False,
    )
    payments_app = create_payments_app(
        db_path=data_dir / "payments.db",
        bus_db_path=bus_db,
        start_background_workers=False,
    )
    orders_app = create_orders_app(
        db_path=data_dir / "orders.db",
        bus_db_path=bus_db,
        clients=OrdersServiceClients(
            cart_url="http://cart.test",
            catalogues_url="http://catalogues.test",
            payments_url="http://payments.test",
            cart_transport=httpx.ASGITransport(app=cart_app),
            catalogues_transport=httpx.ASGITransport(app=catalogues_app),
            payments_transport=httpx.ASGITransport(app=payments_app),
            timeout_seconds=timeout_seconds,
        ),
        start_background_workers=False,
    )
    notification_app = create_notification_app(
        db_path=data_dir / "notification.db",
        bus_db_path=bus_db,
        start_background_consumer=False,
    )
    gateway_app = create_api_gateway_app(
        vault_path=vault_path,
        timeout_seconds=timeout_seconds,
        transports={
            "catalogues": httpx.ASGITransport(app=catalogues_app),
            "cart": httpx.ASGITransport(app=cart_app),
            "orders": httpx.ASGITransport(app=orders_app),
            "payments": httpx.ASGITransport(app=payments_app),
            "notification": httpx.ASGITransport(app=notification_app),
        },
    )

    return ZeptoTestMesh(
        data_dir=data_dir,
        vault_path=vault_path,
        catalogues_app=catalogues_app,
        cart_app=cart_app,
        payments_app=payments_app,
        orders_app=orders_app,
        notification_app=notification_app,
        gateway_app=gateway_app,
    )


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def zepto_mesh(tmp_path: Path, monkeypatch) -> ZeptoTestMesh:
    return build_test_mesh(tmp_path, monkeypatch)
