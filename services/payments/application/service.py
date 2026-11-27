"""Payments application use cases."""

from __future__ import annotations

import uuid

from services.payments.domain.models import Payment, PaymentMethod, PaymentStatus
from services.payments.domain.repositories import PaymentRepository
from shared.messaging.outbox import OutboxRelay


class PaymentApplicationService:
    def __init__(self, repo: PaymentRepository, outbox_relay: OutboxRelay) -> None:
        self.repo = repo
        self.outbox_relay = outbox_relay

    def process_payment(
        self,
        *,
        user_id: str,
        order_id: str,
        amount_paise: int,
        method: PaymentMethod,
        payment_token: str,
        idempotency_key: str,
    ) -> Payment:
        existing = self.repo.get_by_idempotency_key(user_id, idempotency_key)
        if existing is not None:
            return existing

        payment = Payment(
            payment_id=f"pay_{uuid.uuid4().hex[:10]}",
            order_id=order_id,
            user_id=user_id,
            amount_paise=amount_paise,
            method=method,
            payment_token=payment_token,
            idempotency_key=idempotency_key,
        )
        payment.process()
        event_type = (
            "PaymentSucceeded" if payment.status == PaymentStatus.SUCCEEDED else "PaymentFailed"
        )
        self.repo.save_with_outbox(payment, event_type)
        self.outbox_relay.flush_once()
        return payment

    def get_payment(self, payment_id: str, user_id: str) -> Payment:
        payment = self.repo.get_by_id(payment_id)
        if payment is None or payment.user_id != user_id:
            raise LookupError(f"Payment '{payment_id}' not found")
        return payment

    def list_by_order(self, order_id: str, user_id: str) -> list[Payment]:
        payments = self.repo.get_by_order_id(order_id)
        return [p for p in payments if p.user_id == user_id]

    def refund_for_cancelled_order(self, order_id: str) -> Payment | None:
        refunded = self.repo.refund_by_order_id(order_id)
        if refunded is not None:
            self.outbox_relay.flush_once()
        return refunded
