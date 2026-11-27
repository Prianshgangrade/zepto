"""API Gateway configuration and downstream client registry."""

from __future__ import annotations

import os
from dataclasses import dataclass

import httpx

from shared.resilience.circuit_breaker import CircuitBreaker
from shared.resilience.http_client import ResilientServiceClient
from shared.security.secrets import SecretsManager
from shared.security.tokens import TokenManager


@dataclass(frozen=True)
class GatewayServiceRegistry:
    catalogues: ResilientServiceClient
    cart: ResilientServiceClient
    orders: ResilientServiceClient
    payments: ResilientServiceClient
    notification: ResilientServiceClient

    def all_clients(self) -> dict[str, ResilientServiceClient]:
        return {
            "catalogues": self.catalogues,
            "cart": self.cart,
            "orders": self.orders,
            "payments": self.payments,
            "notification": self.notification,
        }


def build_gateway_clients(
    token_manager: TokenManager,
    *,
    transports: dict[str, httpx.AsyncBaseTransport] | None = None,
    timeout_seconds: float | None = None,
) -> GatewayServiceRegistry:
    transports = transports or {}
    timeout = timeout_seconds or float(os.environ.get("HTTP_TIMEOUT_SECONDS", "2.5"))
    threshold = int(os.environ.get("CB_FAILURE_THRESHOLD", "3"))
    recovery = float(os.environ.get("CB_RECOVERY_TIMEOUT_SECONDS", "12.0"))

    def make_client(
        name: str,
        default_url: str,
        env_var: str,
        hop_timeout: float | None = None,
    ) -> ResilientServiceClient:
        return ResilientServiceClient(
            caller_service="api-gateway",
            target_service=name,
            base_url=os.environ.get(env_var, default_url),
            token_manager=token_manager,
            circuit_breaker=CircuitBreaker(f"gateway->{name}", threshold, recovery),
            timeout_seconds=hop_timeout or timeout,
            transport=transports.get(name),
        )

    # Outer gateway hop to orchestrating Orders service needs a larger timeout budget
    # so inner service timeouts can degrade gracefully before gateway times out.
    orders_timeout = max(timeout * 2.5, 5.0) if timeout_seconds is None else timeout * 2.0

    return GatewayServiceRegistry(
        catalogues=make_client("catalogues", "http://127.0.0.1:8001", "CATALOGUES_URL"),
        cart=make_client("cart", "http://127.0.0.1:8002", "CART_URL"),
        orders=make_client("orders", "http://127.0.0.1:8003", "ORDERS_URL", hop_timeout=orders_timeout),
        payments=make_client("payments", "http://127.0.0.1:8004", "PAYMENTS_URL"),
        notification=make_client("notification", "http://127.0.0.1:8005", "NOTIFICATION_URL"),
    )


def create_gateway_security() -> tuple[SecretsManager, TokenManager]:
    secrets_mgr = SecretsManager("api-gateway")
    return secrets_mgr, TokenManager(secrets_mgr)
