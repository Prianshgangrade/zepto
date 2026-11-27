"""Catalogues repository port (abstract interface)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.catalogues.domain.models import (
    CatalogueItem,
    ReservedLineItem,
    StockReservationRequestItem,
)


class CatalogueRepository(ABC):
    @abstractmethod
    def seed_if_empty(self, items: list[CatalogueItem]) -> None: ...

    @abstractmethod
    def list_items(self, category: str | None = None, search: str | None = None) -> list[CatalogueItem]: ...

    @abstractmethod
    def get_item(self, product_id: str) -> CatalogueItem | None: ...

    @abstractmethod
    def reserve_for_order(
        self,
        order_id: str,
        items: list[StockReservationRequestItem],
    ) -> list[ReservedLineItem]: ...

    @abstractmethod
    def release_for_order(self, order_id: str) -> int: ...
