"""Payments API v1 routes."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.payments.application.service import PaymentApplicationService
from services.payments.domain.models import Payment, PaymentMethod, PaymentStatus
from shared.security.zero_trust import ZeroTrustContext


class ChargePaymentRequest(BaseModel):
    order_id: str = Field(min_length=3)
    amount_paise: int = Field(gt=0)
    method: PaymentMethod = PaymentMethod.UPI
    payment_token: str = Field(default="zepto@upi", min_length=2)


def _serialize_payment(p: Payment) -> dict:
    return {
        "payment_id": p.payment_id,
        "order_id": p.order_id,
        "user_id": p.user_id,
        "amount_paise": p.amount_paise,
        "amount_inr": round(p.amount_paise / 100.0, 2),
        "method": p.method.value,
        "status": p.status.value,
        "failure_reason": p.failure_reason,
        "created_at": p.created_at,
    }


def create_v1_router(get_service: callable, require_user: callable) -> APIRouter:
    router = APIRouter(prefix="/api/v1/payments", tags=["payments-v1"])

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def process_payment(
        body: ChargePaymentRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        x_simulate_delay_ms: int | None = Header(default=None, alias="X-Simulate-Delay-Ms"),
        ctx: ZeroTrustContext = Depends(require_user),
        svc: PaymentApplicationService = Depends(get_service),
    ):
        if x_simulate_delay_ms and x_simulate_delay_ms > 0:
            await asyncio.sleep(min(x_simulate_delay_ms, 10_000) / 1000.0)

        key = idempotency_key or f"pay-{body.order_id}-{uuid.uuid4().hex[:8]}"
        payment = svc.process_payment(
            user_id=ctx.user.user_id,
            order_id=body.order_id,
            amount_paise=body.amount_paise,
            method=body.method,
            payment_token=body.payment_token,
            idempotency_key=key,
        )
        payload = _serialize_payment(payment)
        if payment.status == PaymentStatus.FAILED:
            return JSONResponse(status_code=status.HTTP_402_PAYMENT_REQUIRED, content=payload)
        return payload

    @router.get("/{payment_id}")
    def get_payment(
        payment_id: str,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: PaymentApplicationService = Depends(get_service),
    ) -> dict:
        try:
            payment = svc.get_payment(payment_id, ctx.user.user_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        return _serialize_payment(payment)

    @router.get("/order/{order_id}")
    def list_order_payments(
        order_id: str,
        ctx: ZeroTrustContext = Depends(require_user),
        svc: PaymentApplicationService = Depends(get_service),
    ) -> dict:
        payments = svc.list_by_order(order_id, ctx.user.user_id)
        return {"items": [_serialize_payment(p) for p in payments]}

    return router
