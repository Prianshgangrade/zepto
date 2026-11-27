"""Cart repository port."""

from __future__ import annotations

from abc import ABC, abstractmethod

from services.cart.domain.models import Cart


class CartRepository(ABC):
    @abstractmethod
    def get_cart(self, user_id: str) -> Cart: ...

    @abstractmethod
    def save_cart(self, cart: Cart) -> None: ...

    @abstractmethod
    def clear_cart(self, user_id: str) -> None: ...
