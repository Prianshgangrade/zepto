"""Catalogues API v2 routes (API Versioning: enriched pricing, delivery ETA, and pagination)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from services.catalogues.application.service import CatalogueApplicationService
from services.catalogues.domain.models import CatalogueItem, ProductNotFoundError
from shared.security.tokens import ServiceClaims


def _serialize_v2_item(item: CatalogueItem) -> dict:
    return {
        "product_id": item.product_id,
        "sku": item.sku,
        "name": item.name,
        "category": item.category,
        "unit_label": item.unit_label,
        "image_emoji": item.image_emoji,
        "stock_qty": item.stock_qty,
        "in_stock": item.stock_qty > 0,
        "pricing": {
            "selling_paise": item.price.paise,
            "selling_inr": item.price.inr,
            "mrp_paise": item.mrp.paise,
            "mrp_inr": item.mrp.inr,
            "discount_percent": item.discount_percent(),
        },
        "fulfillment": {
            "eta_minutes": item.eta_minutes,
            "promise": f"{item.eta_minutes} mins",
        },
    }


def create_v2_router(
    get_service: callable,
    require_read_caller: callable,
) -> APIRouter:
    router = APIRouter(prefix="/api/v2/catalogues", tags=["catalogues-v2"])

    @router.get("/products")
    def list_products_v2(
        category: str | None = Query(default=None),
        search: str | None = Query(default=None),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=24, ge=1, le=100),
        _: ServiceClaims = Depends(require_read_caller),
        svc: CatalogueApplicationService = Depends(get_service),
    ) -> dict:
        all_items = svc.list_products(category=category, search=search)
        categories = sorted({item.category for item in svc.list_products()})
        start = (page - 1) * page_size
        paged = all_items[start : start + page_size]
        return {
            "api_version": "v2",
            "degraded": False,
            "categories": categories,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total": len(all_items),
            },
            "items": [_serialize_v2_item(i) for i in paged],
        }

    @router.get("/products/{product_id}")
    def get_product_v2(
        product_id: str,
        _: ServiceClaims = Depends(require_read_caller),
        svc: CatalogueApplicationService = Depends(get_service),
    ) -> dict:
        try:
            item = svc.get_product(product_id)
        except ProductNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _serialize_v2_item(item)

    return router
