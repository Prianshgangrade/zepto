"""Orders DDD aggregate root, entities, and state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    PAYMENT_PENDING = "PAYMENT_PENDING"
    CONFIRMED = "CONFIRMED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    CANCELLED = "CANCELLED"


class InvalidOrderTransitionError(ValueError):
    """Raised when an invalid Order state transition is attempted."""


@dataclass(frozen=True)
class OrderItem:
    product_id: str
    name: str
    unit_label: str
    unit_price_paise: int
    quantity: int
    image_emoji: str = "🛒"

    @property
    def line_total_paise(self) -> int:
        return self.unit_price_paise * self.quantity


@dataclass
class Order:
    order_id: str
    user_id: str
    idempotency_key: str
    delivery_address: str
    payment_method: str
    items: list[OrderItem]
    status: OrderStatus = OrderStatus.PAYMENT_PENDING
    payment_id: str | None = None
    failure_reason: str | None = None
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("Order must contain at least one item")
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    @property
    def total_paise(self) -> int:
        return sum(i.line_total_paise for i in self.items)

    def confirm(self, payment_id: str) -> bool:
        """Returns True if transitioned to CONFIRMED, False if already CONFIRMED (idempotent)."""
        if self.status == OrderStatus.CONFIRMED:
            return False
        if self.status not in (OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING):
            raise InvalidOrderTransitionError(
                f"Cannot confirm order in status '{self.status.value}'"
            )
        self.status = OrderStatus.CONFIRMED
        self.payment_id = payment_id
        self.failure_reason = None
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def mark_payment_failed(self, reason: str, payment_id: str | None = None) -> bool:
        """Returns True if transitioned to PAYMENT_FAILED, False if already PAYMENT_FAILED."""
        if self.status == OrderStatus.PAYMENT_FAILED:
            return False
        if self.status not in (OrderStatus.CREATED, OrderStatus.PAYMENT_PENDING):
            raise InvalidOrderTransitionError(
                f"Cannot fail payment for order in status '{self.status.value}'"
            )
        self.status = OrderStatus.PAYMENT_FAILED
        self.payment_id = payment_id or self.payment_id
        self.failure_reason = reason
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return True

    def cancel(self, reason: str = "Cancelled by customer") -> bool:
        """Returns True if transitioned to CANCELLED, False if already CANCELLED."""
        if self.status == OrderStatus.CANCELLED:
            return False
        if self.status == OrderStatus.PAYMENT_FAILED:
            raise InvalidOrderTransitionError("Cannot cancel an order whose payment already failed")
        self.status = OrderStatus.CANCELLED
        self.failure_reason = reason
        self.updated_at = datetime.now(timezone.utc).isoformat()
        return True
