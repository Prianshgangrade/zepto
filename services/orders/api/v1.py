"""Orders API v1 routes."""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.orders.application.service import (
    EmptyCartError,
    OrderActionResult,
    OrderApplicationService,
)
from services.orders.domain.models import InvalidOrderTransitionError, Order
from services.orders.infrastructure.clients import StockConflictError
from shared.resilience.circuit_breaker import CircuitBreakerOpenError
from shared.resilience.http_client import DownstreamServiceError
from shared.security.zero_trust import ZeroTrustContext


class PlaceOrderRequest(BaseModel):
    delivery_address: str = Field(default="221B Zepto Dark Store Zone, Bengaluru", min_length=5)
    payment_method: str = Field(default="UPI", pattern="^(UPI|CARD|WALLET)$")
    payment_token: str = Field(default="zepto@upi", min_length=2)


class RetryPaymentRequest(BaseModel):
    payment_method: str = Field(default="UPI", pattern="^(UPI|CARD|WALLET)$")
    payment_token: str = Field(default="zepto@upi", min_length=2)


def _serialize_order(order: Order, degraded: bool = False, degraded_reason: str | None = None) -> dict:
    return {
        "api_version": "v1",
        "order_id": order.order_id,
        "user_id": order.user_id,
        "delivery_address": order.delivery_address,
        "payment_method": order.payment_method,
        "status": order.status.value,
        "payment_id": order.payment_id,
        "failure_reason": order.failure_reason,
        "total_paise": order.total_paise,
        "total_inr": round(order.total_paise / 100.0, 2),
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "items": [
            {
                "product_id": i.product_id,
                "name": i.name,
                "unit_label": i.unit_label,
                "unit_price_paise": i.unit_price_paise,
                "line_total_paise": i.line_total_paise,
                "quantity": i.quantity,
                "image_emoji": i.image_emoji,
            }
            for i in order.items
        ],
    }


def _to_action_response(result: OrderActionResult, success_status: int = status.HTTP_201_CREATED):
    body = _serialize_order(result.order, result.degraded, result.degraded_reason)
    if result.degraded:
        return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=body)
    return JSONResponse(status_code=success_status, content=body)


def create_v1_router(get_service: callable, require_user: callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1/orders", tags=["orders-v1"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def place_order(
        body: PlaceOrderRequest,
        authorization: str = Header(..., alias="Authorization"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_simulate_delay_ms: int | None = Header(default=None, alias="X-Simulate-Delay-Ms"),
        ctx: ZeroTrustContext = Depends(require_user),
        svc: OrderApplicationService = Depends(get_service),
    ):
        key = idempotency_key or str(uuid.uuid4())
        try:
            result = await svc.place_order(
                user_id=ctx.user.user_id,
                user_auth=authorization,
                idempotency_key=key,
                delivery_address=body.delivery_address,
                payment_method=body.payment_method,
                payment_token=body.payment_token,
                simulate_delay_ms=x_simulate_delay_ms,
            )
        except EmptyCartError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except StockConflictError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Upstream dependency temporarily unavailable: {exc}",
            ) from exc
        return _to_action_response(result, status.HTTP_201_CREATED)

    @router.get("")
    def list_orders(
        ctx: ZeroTrustContext = Depends(require_user),
        svc: OrderApplicationService = Depends(get_service),
    ) -> dict:
        orders = svc.list_orders(ctx.user.user_id)
        return {"api_version": "v1", "items": [_serialize_order(o) for o in orders]}

    @router.get("/{order_id}")
    def get_order(
        order_id: str,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: OrderApplicationService = Depends(get_service),
    ) -> dict:
        try:
            order = svc.get_order(order_id, ctx.user.user_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _serialize_order(order)

    @router.post("/{order_id}/retry-payment")
    async def retry_payment(
        order_id: str,
        body: RetryPaymentRequest,
        authorization: str = Header(..., alias="Authorization"),
        x_simulate_delay_ms: int | None = Header(default=None, alias="X-Simulate-Delay-Ms"),
        ctx: ZeroTrustContext = Depends(require_user),
        svc: OrderApplicationService = Depends(get_service),
    ):
        try:
            result = await svc.retry_payment(
                user_id=ctx.user.user_id,
                order_id=order_id,
                user_auth=authorization,
                payment_method=body.payment_method,
                payment_token=body.payment_token,
                simulate_delay_ms=x_simulate_delay_ms,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return _to_action_response(result, status.HTTP_200_OK)

    @router.post("/{order_id}/cancel")
    def cancel_order(
        order_id: str,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: OrderApplicationService = Depends(get_service),
    ) -> dict:
        try:
            order = svc.cancel_order(order_id, ctx.user.user_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except InvalidOrderTransitionError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        return _serialize_order(order)

    return router
