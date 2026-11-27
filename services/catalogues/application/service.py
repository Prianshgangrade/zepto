"""Catalogues application use cases (Single Responsibility Principle)."""

from __future__ import annotations

from services.catalogues.domain.models import (
    CatalogueItem,
    Money,
    ProductNotFoundError,
    ReservedLineItem,
    StockReservationRequestItem,
)
from services.catalogues.domain.repositories import CatalogueRepository


DEFAULT_ZEPTO_CATALOGUE: list[CatalogueItem] = [
    CatalogueItem("prod_milk", "ZEP-DAI-001", "Amul Taaza Toned Milk", "Dairy & Bread", "500 ml", Money(2700), Money(2800), 45, 10, "🥛"),
    CatalogueItem("prod_bread", "ZEP-DAI-002", "Harvest Gold Brown Bread", "Dairy & Bread", "400 g", Money(4800), Money(5500), 30, 10, "🍞"),
    CatalogueItem("prod_eggs", "ZEP-DAI-003", "Farm Fresh White Eggs", "Dairy & Bread", "6 pcs", Money(5400), Money(6500), 28, 10, "🥚"),
    CatalogueItem("prod_curd", "ZEP-DAI-004", "Mother Dairy Classic Curd", "Dairy & Bread", "400 g", Money(3500), Money(4000), 35, 10, "🥣"),
    CatalogueItem("prod_banana", "ZEP-FRV-001", "Robusta Banana", "Fruits & Veggies", "500 g", Money(3200), Money(4200), 50, 9, "🍌"),
    CatalogueItem("prod_tomato", "ZEP-FRV-002", "Desi Red Tomato", "Fruits & Veggies", "500 g", Money(2400), Money(3400), 60, 9, "🍅"),
    CatalogueItem("prod_coriander", "ZEP-FRV-003", "Fresh Coriander Bunch", "Fruits & Veggies", "100 g", Money(1500), Money(2200), 40, 8, "🌿"),
    CatalogueItem("prod_mango", "ZEP-FRV-004", "Alphonso Mango", "Fruits & Veggies", "2 pcs", Money(14900), Money(18900), 20, 10, "🥭"),
    CatalogueItem("prod_chips", "ZEP-SNK-001", "Lay's India's Magic Masala", "Snacks & Drinks", "50 g", Money(2000), Money(2000), 75, 10, "🥔"),
    CatalogueItem("prod_cola", "ZEP-SNK-002", "Coca-Cola Zero Sugar Can", "Snacks & Drinks", "300 ml", Money(4000), Money(4000), 55, 10, "🥤"),
    CatalogueItem("prod_rice", "ZEP-STP-001", "India Gate Basmati Rice", "Staples", "1 kg", Money(13900), Money(16500), 25, 12, "🌾"),
    CatalogueItem("prod_oil", "ZEP-STP-002", "Fortune Sunlite Refined Oil", "Staples", "1 L", Money(14500), Money(17000), 22, 12, "🌻"),
]


class CatalogueApplicationService:
    def __init__(self, repo: CatalogueRepository) -> None:
        self.repo = repo

    def seed_defaults(self) -> None:
        self.repo.seed_if_empty(DEFAULT_ZEPTO_CATALOGUE)

    def list_products(
        self,
        category: str | None = None,
        search: str | None = None,
    ) -> list[CatalogueItem]:
        return self.repo.list_items(category=category, search=search)

    def get_product(self, product_id: str) -> CatalogueItem:
        item = self.repo.get_item(product_id)
        if item is None:
            raise ProductNotFoundError(f"Product '{product_id}' not found")
        return item

    def reserve_stock(
        self,
        order_id: str,
        items: list[StockReservationRequestItem],
    ) -> list[ReservedLineItem]:
        if not items:
            raise ValueError("Reservation items cannot be empty")
        return self.repo.reserve_for_order(order_id, items)

    def release_stock(self, order_id: str) -> int:
        return self.repo.release_for_order(order_id)
