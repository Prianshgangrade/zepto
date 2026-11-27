"""Cart DDD aggregate root and entity models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CartItem:
    product_id: str
    name: str
    unit_label: str
    unit_price_paise: int
    image_emoji: str
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0 or self.quantity > 50:
            raise ValueError("Cart item quantity must be between 1 and 50")
        if self.unit_price_paise < 0:
            raise ValueError("Unit price cannot be negative")

    @property
    def line_total_paise(self) -> int:
        return self.unit_price_paise * self.quantity


@dataclass
class Cart:
    user_id: str
    items: list[CartItem] = field(default_factory=list)

    @property
    def total_items(self) -> int:
        return sum(i.quantity for i in self.items)

    @property
    def total_paise(self) -> int:
        return sum(i.line_total_paise for i in self.items)

    def find_item(self, product_id: str) -> CartItem | None:
        return next((i for i in self.items if i.product_id == product_id), None)

    def add_item(
        self,
        *,
        product_id: str,
        name: str,
        unit_label: str,
        unit_price_paise: int,
        image_emoji: str,
        quantity: int,
    ) -> None:
        if quantity <= 0:
            raise ValueError("Quantity to add must be positive")
        existing = self.find_item(product_id)
        if existing is not None:
            new_qty = existing.quantity + quantity
            if new_qty > 50:
                raise ValueError("Maximum 50 units allowed per item")
            existing.quantity = new_qty
            existing.name = name
            existing.unit_label = unit_label
            existing.unit_price_paise = unit_price_paise
            existing.image_emoji = image_emoji
            return
        self.items.append(
            CartItem(
                product_id=product_id,
                name=name,
                unit_label=unit_label,
                unit_price_paise=unit_price_paise,
                image_emoji=image_emoji,
                quantity=quantity,
            )
        )

    def set_quantity(self, product_id: str, quantity: int) -> None:
        if quantity < 0 or quantity > 50:
            raise ValueError("Quantity must be between 0 and 50")
        if quantity == 0:
            self.items = [i for i in self.items if i.product_id != product_id]
            return
        existing = self.find_item(product_id)
        if existing is None:
            raise LookupError(f"Product '{product_id}' is not in cart")
        existing.quantity = quantity

    def clear(self) -> None:
        self.items = []
