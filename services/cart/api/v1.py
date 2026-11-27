"""Cart API v1 routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services.cart.application.service import (
    CartApplicationService,
    CartProductUnavailableError,
    CartView,
)
from shared.security.zero_trust import ZeroTrustContext


class AddCartItemRequest(BaseModel):
    product_id: str = Field(min_length=2)
    quantity: int = Field(default=1, gt=0, le=50)


class UpdateCartItemRequest(BaseModel):
    quantity: int = Field(ge=0, le=50)


def _serialize_cart_view(view: CartView) -> dict:
    return {
        "api_version": "v1",
        "user_id": view.cart.user_id,
        "total_items": view.cart.total_items,
        "total_paise": view.cart.total_paise,
        "total_inr": round(view.cart.total_paise / 100.0, 2),
        "degraded": view.degraded,
        "degraded_reason": view.degraded_reason,
        "items": [
            {
                "product_id": i.product_id,
                "name": i.name,
                "unit_label": i.unit_label,
                "unit_price_paise": i.unit_price_paise,
                "unit_price_inr": round(i.unit_price_paise / 100.0, 2),
                "line_total_paise": i.line_total_paise,
                "image_emoji": i.image_emoji,
                "quantity": i.quantity,
            }
            for i in view.cart.items
        ],
    }


def create_v1_router(get_service: callable, require_user: callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1/cart", tags=["cart-v1"])

    @router.get("")
    async def get_cart(
        ctx: ZeroTrustContext = Depends(require_user),
        svc: CartApplicationService = Depends(get_service),
    ) -> dict:
        view = await svc.get_cart(ctx.user.user_id)
        return _serialize_cart_view(view)

    @router.post("/items", status_code=status.HTTP_201_CREATED)
    async def add_item(
        body: AddCartItemRequest,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: CartApplicationService = Depends(get_service),
    ) -> dict:
        try:
            view = await svc.add_item(ctx.user.user_id, body.product_id, body.quantity)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (CartProductUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
        return _serialize_cart_view(view)

    @router.patch("/items/{product_id}")
    async def update_item(
        product_id: str,
        body: UpdateCartItemRequest,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: CartApplicationService = Depends(get_service),
    ) -> dict:
        try:
            view = await svc.set_item_quantity(ctx.user.user_id, product_id, body.quantity)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except (CartProductUnavailableError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return _serialize_cart_view(view)

    @router.delete("/items/{product_id}")
    async def remove_item(
        product_id: str,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: CartApplicationService = Depends(get_service),
    ) -> dict:
        view = await svc.set_item_quantity(ctx.user.user_id, product_id, 0)
        return _serialize_cart_view(view)

    @router.delete("")
    async def clear_cart(
        ctx: ZeroTrustContext = Depends(require_user),
        svc: CartApplicationService = Depends(get_service),
    ) -> dict:
        view = svc.clear_cart(ctx.user.user_id)
        return _serialize_cart_view(view)

    return router
