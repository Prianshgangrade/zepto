"""Resilient synchronous HTTP clients from Orders -> Cart, Catalogues, and Payments."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from services.orders.domain.models import OrderItem
from shared.resilience.circuit_breaker import CircuitBreaker
from shared.resilience.http_client import ResilientServiceClient
from shared.security.secrets import SecretsManager
from shared.security.tokens import TokenManager


class StockConflictError(ValueError):
    """Raised when Catalogues rejects reservation due to insufficient stock."""


@dataclass(frozen=True)
class PaymentAttemptResult:
    payment_id: str | None
    status: str
    failure_reason: str | None = None


class OrdersServiceClients:
    """Holds isolated resilient HTTP clients with independent Circuit Breakers per dependency."""

    def __init__(
        self,
        *,
        cart_url: str | None = None,
        catalogues_url: str | None = None,
        payments_url: str | None = None,
        cart_transport: httpx.AsyncBaseTransport | None = None,
        catalogues_transport: httpx.AsyncBaseTransport | None = None,
        payments_transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        token_mgr = TokenManager(SecretsManager("orders"))
        timeout = timeout_seconds or float(os.environ.get("HTTP_TIMEOUT_SECONDS", "2.5"))
        threshold = int(os.environ.get("CB_FAILURE_THRESHOLD", "3"))
        recovery = float(os.environ.get("CB_RECOVERY_TIMEOUT_SECONDS", "12.0"))

        self.cart = ResilientServiceClient(
            caller_service="orders",
            target_service="cart",
            base_url=cart_url or os.environ.get("CART_URL", "http://127.0.0.1:8002"),
            token_manager=token_mgr,
            circuit_breaker=CircuitBreaker("orders->cart", threshold, recovery),
            timeout_seconds=timeout,
            transport=cart_transport,
        )
        self.catalogues = ResilientServiceClient(
            caller_service="orders",
            target_service="catalogues",
            base_url=catalogues_url or os.environ.get("CATALOGUES_URL", "http://127.0.0.1:8001"),
            token_manager=token_mgr,
            circuit_breaker=CircuitBreaker("orders->catalogues", threshold, recovery),
            timeout_seconds=timeout,
            transport=catalogues_transport,
        )
        self.payments = ResilientServiceClient(
            caller_service="orders",
            target_service="payments",
            base_url=payments_url or os.environ.get("PAYMENTS_URL", "http://127.0.0.1:8004"),
            token_manager=token_mgr,
            circuit_breaker=CircuitBreaker("orders->payments", threshold, recovery),
            timeout_seconds=timeout,
            transport=payments_transport,
        )

    async def fetch_user_cart_items(self, user_auth: str) -> list[dict]:
        resp = await self.cart.request("GET", "/api/v1/cart", user_authorization=user_auth)
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def reserve_catalogue_stock(
        self,
        order_id: str,
        items: list[dict],
    ) -> list[OrderItem]:
        resp = await self.catalogues.request(
            "POST",
            "/api/v1/catalogues/reservations",
            json_body={
                "order_id": order_id,
                "items": [
                    {"product_id": i["product_id"], "quantity": int(i["quantity"])}
                    for i in items
                ],
            },
        )
        if resp.status_code == 409:
            raise StockConflictError(resp.json().get("detail", "Insufficient stock"))
        if resp.status_code == 404:
            raise LookupError(resp.json().get("detail", "Product not found"))
        resp.raise_for_status()
        data = resp.json()
        return [
            OrderItem(
                product_id=r["product_id"],
                name=r["name"],
                unit_label=r["unit_label"],
                unit_price_paise=int(r["unit_price_paise"]),
                quantity=int(r["quantity"]),
                image_emoji=r.get("image_emoji", "🛒"),
            )
            for r in data["items"]
        ]

    async def charge_payment(
        self,
        *,
        user_auth: str,
        order_id: str,
        amount_paise: int,
        payment_method: str,
        payment_token: str,
        idempotency_key: str,
        simulate_delay_ms: int | None = None,
    ) -> PaymentAttemptResult:
        headers = {"Idempotency-Key": idempotency_key}
        if simulate_delay_ms is not None and simulate_delay_ms > 0:
            headers["X-Simulate-Delay-Ms"] = str(simulate_delay_ms)

        resp = await self.payments.request(
            "POST",
            "/api/v1/payments",
            user_authorization=user_auth,
            headers=headers,
            json_body={
                "order_id": order_id,
                "amount_paise": amount_paise,
                "method": payment_method,
                "payment_token": payment_token,
            },
        )
        if resp.status_code == 402:
            data = resp.json()
            return PaymentAttemptResult(
                payment_id=data.get("payment_id"),
                status="FAILED",
                failure_reason=data.get("failure_reason", "Payment declined"),
            )
        resp.raise_for_status()
        data = resp.json()
        return PaymentAttemptResult(
            payment_id=data.get("payment_id"),
            status=data.get("status", "SUCCEEDED"),
            failure_reason=data.get("failure_reason"),
        )
