"""Payments DDD domain models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum


class PaymentMethod(str, Enum):
    UPI = "UPI"
    CARD = "CARD"
    WALLET = "WALLET"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


@dataclass
class Payment:
    payment_id: str
    order_id: str
    user_id: str
    amount_paise: int
    method: PaymentMethod
    payment_token: str
    idempotency_key: str
    status: PaymentStatus = PaymentStatus.INITIATED
    failure_reason: str | None = None
    created_at: str = ""

    def __post_init__(self) -> None:
        if self.amount_paise <= 0:
            raise ValueError("Payment amount must be positive")
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def process(self) -> None:
        if self.status != PaymentStatus.INITIATED:
            return
        token = self.payment_token.strip().lower()
        if token.startswith("fail") or token.startswith("decline"):
            self.status = PaymentStatus.FAILED
            self.failure_reason = "Payment declined by issuer"
        else:
            self.status = PaymentStatus.SUCCEEDED
            self.failure_reason = None

    def refund(self) -> bool:
        if self.status != PaymentStatus.SUCCEEDED:
            return False
        self.status = PaymentStatus.REFUNDED
        return True
