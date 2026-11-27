"""Catalogues API v1 routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from services.catalogues.application.service import CatalogueApplicationService
from services.catalogues.domain.models import (
    CatalogueItem,
    InsufficientStockError,
    ProductNotFoundError,
    StockReservationRequestItem,
)
from shared.security.tokens import ServiceClaims


class ReserveItemInput(BaseModel):
    product_id: str
    quantity: int = Field(gt=0, le=50)


class ReserveStockRequest(BaseModel):
    order_id: str = Field(min_length=3)
    items: list[ReserveItemInput] = Field(min_length=1)


def _serialize_v1_item(item: CatalogueItem) -> dict:
    return {
        "product_id": item.product_id,
        "sku": item.sku,
        "name": item.name,
        "category": item.category,
        "unit_label": item.unit_label,
        "price_paise": item.price.paise,
        "price_inr": item.price.inr,
        "stock_qty": item.stock_qty,
        "in_stock": item.stock_qty > 0,
        "image_emoji": item.image_emoji,
    }


def create_v1_router(
    get_service: callable,
    require_read_caller: callable,
    require_orders_caller: callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/catalogues", tags=["catalogues-v1"])

    @router.get("/products")
    def list_products_v1(
        category: str | None = Query(default=None),
        search: str | None = Query(default=None),
        _: ServiceClaims = Depends(require_read_caller),
        svc: CatalogueApplicationService = Depends(get_service),
    ) -> dict:
        items = svc.list_products(category=category, search=search)
        return {
            "api_version": "v1",
            "degraded": False,
            "items": [_serialize_v1_item(i) for i in items],
        }

    @router.get("/products/{product_id}")
    def get_product_v1(
        product_id: str,
        _: ServiceClaims = Depends(require_read_caller),
        svc: CatalogueApplicationService = Depends(get_service),
    ) -> dict:
        try:
            item = svc.get_product(product_id)
        except ProductNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _serialize_v1_item(item)

    @router.post("/reservations", status_code=status.HTTP_201_CREATED)
    def reserve_stock_v1(
        body: ReserveStockRequest,
        caller: ServiceClaims = Depends(require_orders_caller),
        svc: CatalogueApplicationService = Depends(get_service),
    ) -> dict:
        if caller.caller_service != "orders":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Zero-Trust policy: '{caller.caller_service}' cannot reserve stock",
            )
        try:
            reserved = svc.reserve_stock(
                order_id=body.order_id,
                items=[StockReservationRequestItem(i.product_id, i.quantity) for i in body.items],
            )
        except ProductNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InsufficientStockError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

        return {
            "order_id": body.order_id,
            "status": "RESERVED",
            "items": [
                {
                    "product_id": r.product_id,
                    "name": r.name,
                    "unit_label": r.unit_label,
                    "unit_price_paise": r.unit_price_paise,
                    "quantity": r.quantity,
                    "image_emoji": r.image_emoji,
                }
                for r in reserved
            ],
        }

    return router
