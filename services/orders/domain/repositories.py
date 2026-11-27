"""Orders repository port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.orders.domain.models import Order


class OrderRepository(ABC):
    @abstractmethod
    def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Order | None: ...

    @abstractmethod
    def get_by_id(self, order_id: str) -> Order | None: ...

    @abstractmethod
    def list_for_user(self, user_id: str) -> list[Order]: ...

    @abstractmethod
    def create_with_outbox(self, order: Order) -> None: ...

    @abstractmethod
    def update_with_outbox(self, order: Order, event_type: str | None = None) -> None: ...
