"""Payments repository port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.payments.domain.models import Payment


class PaymentRepository(ABC):
    @abstractmethod
    def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Payment | None: ...

    @abstractmethod
    def get_by_id(self, payment_id: str) -> Payment | None: ...

    @abstractmethod
    def get_by_order_id(self, order_id: str) -> list[Payment]: ...

    @abstractmethod
    def save_with_outbox(self, payment: Payment, event_type: str) -> None: ...

    @abstractmethod
    def refund_by_order_id(self, order_id: str) -> Payment | None: ...
