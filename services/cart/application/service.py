"""Cart application use cases with Circuit Breaker & Graceful Degradation."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from services.cart.domain.models import Cart
from services.cart.domain.repositories import CartRepository
from services.cart.infrastructure.catalogues_client import CataloguesClient
from shared.resilience.circuit_breaker import CircuitBreakerOpenError
from shared.resilience.http_client import DownstreamServiceError


@dataclass(frozen=True)
class CartView:
    cart: Cart
    degraded: bool = False
    degraded_reason: str | None = None


class CartProductUnavailableError(ValueError):
    """Raised when a product does not exist or lacks stock."""


class CartApplicationService:
    def __init__(self, repo: CartRepository, catalogues_client: CataloguesClient) -> None:
        self.repo = repo
        self.catalogues_client = catalogues_client

    async def get_cart(self, user_id: str, refresh_catalogue: bool = True) -> CartView:
        cart = self.repo.get_cart(user_id)
        if not cart.items or not refresh_catalogue:
            return CartView(cart=cart)

        degraded = False
        reason: str | None = None
        updated = False
        for item in cart.items:
            try:
                snap = await self.catalogues_client.fetch_product(item.product_id)
                if snap is not None and (
                    snap.price_paise != item.unit_price_paise or snap.name != item.name
                ):
                    item.unit_price_paise = snap.price_paise
                    item.name = snap.name
                    item.unit_label = snap.unit_label
                    item.image_emoji = snap.image_emoji
                    updated = True
            except (
                CircuitBreakerOpenError,
                DownstreamServiceError,
                httpx.TimeoutException,
                httpx.TransportError,
            ):
                degraded = True
                reason = "Catalogues temporarily unavailable; showing cached item prices"
                break

        if updated:
            self.repo.save_cart(cart)
        return CartView(cart=cart, degraded=degraded, degraded_reason=reason)

    async def add_item(self, user_id: str, product_id: str, quantity: int) -> CartView:
        cart = self.repo.get_cart(user_id)
        existing = cart.find_item(product_id)

        try:
            snap = await self.catalogues_client.fetch_product(product_id)
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            # Graceful Degradation: allow incrementing an item already cached in user's cart
            if existing is not None:
                cart.add_item(
                    product_id=existing.product_id,
                    name=existing.name,
                    unit_label=existing.unit_label,
                    unit_price_paise=existing.unit_price_paise,
                    image_emoji=existing.image_emoji,
                    quantity=quantity,
                )
                self.repo.save_cart(cart)
                return CartView(
                    cart=cart,
                    degraded=True,
                    degraded_reason="Catalogues temporarily unavailable; updated using cached item snapshot",
                )
            raise RuntimeError("Catalogues service unavailable; cannot verify new item") from exc

        if snap is None:
            raise LookupError(f"Product '{product_id}' not found")
        target_qty = (existing.quantity if existing else 0) + quantity
        if snap.stock_qty < target_qty:
            raise CartProductUnavailableError(
                f"Only {snap.stock_qty} unit(s) of '{snap.name}' left in stock"
            )

        cart.add_item(
            product_id=snap.product_id,
            name=snap.name,
            unit_label=snap.unit_label,
            unit_price_paise=snap.price_paise,
            image_emoji=snap.image_emoji,
            quantity=quantity,
        )
        self.repo.save_cart(cart)
        return CartView(cart=cart)

    async def set_item_quantity(self, user_id: str, product_id: str, quantity: int) -> CartView:
        cart = self.repo.get_cart(user_id)
        if quantity == 0:
            cart.set_quantity(product_id, 0)
            self.repo.save_cart(cart)
            return CartView(cart=cart)

        degraded = False
        reason: str | None = None
        try:
            snap = await self.catalogues_client.fetch_product(product_id)
            if snap is None:
                raise LookupError(f"Product '{product_id}' not found")
            if snap.stock_qty < quantity:
                raise CartProductUnavailableError(
                    f"Only {snap.stock_qty} unit(s) of '{snap.name}' left in stock"
                )
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ):
            degraded = True
            reason = "Catalogues temporarily unavailable; quantity updated using cached cart snapshot"

        cart.set_quantity(product_id, quantity)
        self.repo.save_cart(cart)
        return CartView(cart=cart, degraded=degraded, degraded_reason=reason)

    def clear_cart(self, user_id: str) -> CartView:
        self.repo.clear_cart(user_id)
        return CartView(cart=Cart(user_id=user_id, items=[]))
