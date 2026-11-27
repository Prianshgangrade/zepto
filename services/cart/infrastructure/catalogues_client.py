"""Resilient synchronous HTTP client for Cart -> Catalogues lookups."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from shared.resilience.circuit_breaker import CircuitBreaker
from shared.resilience.http_client import ResilientServiceClient
from shared.security.secrets import SecretsManager
from shared.security.tokens import TokenManager


@dataclass(frozen=True)
class CatalogueProductSnapshot:
    product_id: str
    name: str
    unit_label: str
    price_paise: int
    stock_qty: int
    image_emoji: str


class CataloguesClient:
    def __init__(
        self,
        base_url: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        token_mgr = TokenManager(SecretsManager("cart"))
        resolved_url = base_url or os.environ.get("CATALOGUES_URL", "http://127.0.0.1:8001")
        resolved_timeout = timeout_seconds or float(os.environ.get("HTTP_TIMEOUT_SECONDS", "2.5"))
        self.client = ResilientServiceClient(
            caller_service="cart",
            target_service="catalogues",
            base_url=resolved_url,
            token_manager=token_mgr,
            circuit_breaker=circuit_breaker
            or CircuitBreaker(
                name="cart->catalogues",
                failure_threshold=int(os.environ.get("CB_FAILURE_THRESHOLD", "3")),
                recovery_timeout_seconds=float(os.environ.get("CB_RECOVERY_TIMEOUT_SECONDS", "12.0")),
            ),
            timeout_seconds=resolved_timeout,
            transport=transport,
        )

    async def fetch_product(self, product_id: str) -> CatalogueProductSnapshot | None:
        resp = await self.client.request("GET", f"/api/v2/catalogues/products/{product_id}")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        return CatalogueProductSnapshot(
            product_id=data["product_id"],
            name=data["name"],
            unit_label=data["unit_label"],
            price_paise=int(data["pricing"]["selling_paise"]),
            stock_qty=int(data["stock_qty"]),
            image_emoji=data.get("image_emoji", "🛒"),
        )
