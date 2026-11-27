"""Catalogues DDD domain models: Value Objects, Aggregates, and Invariants."""

from __future__ import annotations

from dataclasses import dataclass


class InsufficientStockError(ValueError):
    """Raised when attempting to reserve more units than available in dark-store stock."""


class ProductNotFoundError(LookupError):
    """Raised when a requested catalogue product does not exist."""


@dataclass(frozen=True)
class Money:
    paise: int

    def __post_init__(self) -> None:
        if self.paise < 0:
            raise ValueError("Money amount cannot be negative")

    @property
    def inr(self) -> float:
        return round(self.paise / 100.0, 2)


@dataclass
class CatalogueItem:
    """Aggregate root representing a quick-commerce grocery item in the catalogue."""

    product_id: str
    sku: str
    name: str
    category: str
    unit_label: str
    price: Money
    mrp: Money
    stock_qty: int
    eta_minutes: int = 10
    image_emoji: str = "🛒"

    def __post_init__(self) -> None:
        if self.stock_qty < 0:
            raise ValueError("Stock quantity cannot be negative")
        if self.mrp.paise < self.price.paise:
            raise ValueError("MRP cannot be lower than selling price")

    def discount_percent(self) -> int:
        if self.mrp.paise <= 0 or self.mrp.paise <= self.price.paise:
            return 0
        return round(((self.mrp.paise - self.price.paise) / self.mrp.paise) * 100)

    def reserve_stock(self, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("Reservation quantity must be positive")
        if self.stock_qty < quantity:
            raise InsufficientStockError(
                f"Insufficient stock for '{self.name}': requested {quantity}, available {self.stock_qty}"
            )
        self.stock_qty -= quantity

    def release_stock(self, quantity: int) -> None:
        if quantity <= 0:
            raise ValueError("Release quantity must be positive")
        self.stock_qty += quantity


@dataclass(frozen=True)
class StockReservationRequestItem:
    product_id: str
    quantity: int


@dataclass(frozen=True)
class ReservedLineItem:
    product_id: str
    name: str
    unit_label: str
    unit_price_paise: int
    quantity: int
    image_emoji: str
