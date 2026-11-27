"""Orders application use cases: Checkout Saga, Graceful Degradation, Idempotency."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import httpx

from services.orders.domain.models import Order, OrderStatus
from services.orders.domain.repositories import OrderRepository
from services.orders.infrastructure.clients import OrdersServiceClients
from shared.messaging.outbox import OutboxRelay
from shared.resilience.circuit_breaker import CircuitBreakerOpenError
from shared.resilience.http_client import DownstreamServiceError


class EmptyCartError(ValueError):
    """Raised when checking out with an empty cart."""


@dataclass(frozen=True)
class OrderActionResult:
    order: Order
    degraded: bool = False
    degraded_reason: str | None = None


class OrderApplicationService:
    def __init__(
        self,
        repo: OrderRepository,
        clients: OrdersServiceClients,
        outbox_relay: OutboxRelay,
    ) -> None:
        self.repo = repo
        self.clients = clients
        self.outbox_relay = outbox_relay

    async def place_order(
        self,
        *,
        user_id: str,
        user_auth: str,
        idempotency_key: str,
        delivery_address: str,
        payment_method: str,
        payment_token: str,
        simulate_delay_ms: int | None = None,
    ) -> OrderActionResult:
        existing = self.repo.get_by_idempotency_key(user_id, idempotency_key)
        if existing is not None:
            return OrderActionResult(order=existing)

        cart_items = await self.clients.fetch_user_cart_items(user_auth)
        if not cart_items:
            raise EmptyCartError("Your cart is empty")

        order_id = f"ord_{uuid.uuid4().hex[:10]}"
        reserved_items = await self.clients.reserve_catalogue_stock(order_id, cart_items)

        order = Order(
            order_id=order_id,
            user_id=user_id,
            idempotency_key=idempotency_key,
            delivery_address=delivery_address,
            payment_method=payment_method,
            items=reserved_items,
            status=OrderStatus.PAYMENT_PENDING,
        )
        # Atomically persist order + OrderCreated event in outbox (Cart & Notification consume asynchronously)
        self.repo.create_with_outbox(order)
        self.outbox_relay.flush_once()

        return await self._attempt_payment(
            order=order,
            user_auth=user_auth,
            payment_method=payment_method,
            payment_token=payment_token,
            payment_idem_key=f"pay-{order.order_id}-1",
            simulate_delay_ms=simulate_delay_ms,
        )

    async def retry_payment(
        self,
        *,
        user_id: str,
        order_id: str,
        user_auth: str,
        payment_method: str,
        payment_token: str,
        simulate_delay_ms: int | None = None,
    ) -> OrderActionResult:
        order = self.get_order(order_id, user_id)
        if order.status != OrderStatus.PAYMENT_PENDING:
            raise ValueError(f"Only PAYMENT_PENDING orders can retry payment (current: {order.status.value})")
        return await self._attempt_payment(
            order=order,
            user_auth=user_auth,
            payment_method=payment_method,
            payment_token=payment_token,
            payment_idem_key=f"pay-{order.order_id}-{uuid.uuid4().hex[:6]}",
            simulate_delay_ms=simulate_delay_ms,
        )

    async def _attempt_payment(
        self,
        *,
        order: Order,
        user_auth: str,
        payment_method: str,
        payment_token: str,
        payment_idem_key: str,
        simulate_delay_ms: int | None,
    ) -> OrderActionResult:
        try:
            result = await self.clients.charge_payment(
                user_auth=user_auth,
                order_id=order.order_id,
                amount_paise=order.total_paise,
                payment_method=payment_method,
                payment_token=payment_token,
                idempotency_key=payment_idem_key,
                simulate_delay_ms=simulate_delay_ms,
            )
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ):
            # Graceful Degradation: order stays saved in PAYMENT_PENDING instead of failing catastrophically
            return OrderActionResult(
                order=order,
                degraded=True,
                degraded_reason=(
                    "Payments service temporarily unavailable or timed out; "
                    "order saved as PAYMENT_PENDING for retry or async confirmation"
                ),
            )

        if result.status == "SUCCEEDED" and result.payment_id:
            if order.confirm(result.payment_id):
                self.repo.update_with_outbox(order, event_type="OrderConfirmed")
                self.outbox_relay.flush_once()
        elif result.status == "FAILED":
            if order.mark_payment_failed(
                reason=result.failure_reason or "Payment declined",
                payment_id=result.payment_id,
            ):
                self.repo.update_with_outbox(order, event_type=None)
        return OrderActionResult(order=order)

    def get_order(self, order_id: str, user_id: str) -> Order:
        order = self.repo.get_by_id(order_id)
        if order is None or order.user_id != user_id:
            raise LookupError(f"Order '{order_id}' not found")
        return order

    def list_orders(self, user_id: str) -> list[Order]:
        return self.repo.list_for_user(user_id)

    def cancel_order(self, order_id: str, user_id: str) -> Order:
        order = self.get_order(order_id, user_id)
        if order.cancel():
            self.repo.update_with_outbox(order, event_type="OrderCancelled")
            self.outbox_relay.flush_once()
        return order
