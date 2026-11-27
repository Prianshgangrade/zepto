"""SQLite repository + Transactional Outbox for Payments."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from services.payments.domain.models import Payment, PaymentMethod, PaymentStatus
from services.payments.domain.repositories import PaymentRepository
from services.payments.infrastructure.database import connect_payments_db, init_payments_db
from shared.database.sqlite_base import run_with_retry
from shared.messaging.events import DomainEvent
from shared.messaging.outbox import enqueue_outbox_event


class SQLitePaymentRepository(PaymentRepository):
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = init_payments_db(db_path)

    @staticmethod
    def _row_to_payment(row: sqlite3.Row) -> Payment:
        return Payment(
            payment_id=row["payment_id"],
            order_id=row["order_id"],
            user_id=row["user_id"],
            amount_paise=int(row["amount_paise"]),
            method=PaymentMethod(row["method"]),
            payment_token=row["payment_token"],
            idempotency_key=row["idempotency_key"],
            status=PaymentStatus(row["status"]),
            failure_reason=row["failure_reason"],
            created_at=row["created_at"],
        )

    def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Payment | None:
        def _op() -> Payment | None:
            with connect_payments_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM payments WHERE user_id = ? AND idempotency_key = ?",
                    (user_id, idempotency_key),
                ).fetchone()
                return self._row_to_payment(row) if row else None

        return run_with_retry(_op)

    def get_by_id(self, payment_id: str) -> Payment | None:
        def _op() -> Payment | None:
            with connect_payments_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM payments WHERE payment_id = ?",
                    (payment_id,),
                ).fetchone()
                return self._row_to_payment(row) if row else None

        return run_with_retry(_op)

    def get_by_order_id(self, order_id: str) -> list[Payment]:
        def _op() -> list[Payment]:
            with connect_payments_db(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM payments WHERE order_id = ? ORDER BY created_at DESC",
                    (order_id,),
                ).fetchall()
                return [self._row_to_payment(r) for r in rows]

        return run_with_retry(_op)

    def save_with_outbox(self, payment: Payment, event_type: str) -> None:
        event = DomainEvent(
            event_type=event_type,
            producer="payments",
            correlation_id=payment.order_id,
            payload={
                "payment_id": payment.payment_id,
                "order_id": payment.order_id,
                "user_id": payment.user_id,
                "amount_paise": payment.amount_paise,
                "method": payment.method.value,
                "status": payment.status.value,
                "failure_reason": payment.failure_reason,
            },
        )

        def _op() -> None:
            with connect_payments_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO payments (
                        payment_id, order_id, user_id, amount_paise, method,
                        payment_token, idempotency_key, status, failure_reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        payment.payment_id,
                        payment.order_id,
                        payment.user_id,
                        payment.amount_paise,
                        payment.method.value,
                        payment.payment_token,
                        payment.idempotency_key,
                        payment.status.value,
                        payment.failure_reason,
                        payment.created_at,
                    ),
                )
                enqueue_outbox_event(conn, "payments.events", event)

        run_with_retry(_op)

    def refund_by_order_id(self, order_id: str) -> Payment | None:
        def _op() -> Payment | None:
            with connect_payments_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT * FROM payments
                    WHERE order_id = ? AND status = 'SUCCEEDED'
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (order_id,),
                ).fetchone()
                if not row:
                    return None
                payment = self._row_to_payment(row)
                if not payment.refund():
                    return None
                conn.execute(
                    "UPDATE payments SET status = ? WHERE payment_id = ?",
                    (payment.status.value, payment.payment_id),
                )
                enqueue_outbox_event(
                    conn,
                    "payments.events",
                    DomainEvent(
                        event_type="PaymentRefunded",
                        producer="payments",
                        correlation_id=payment.order_id,
                        payload={
                            "payment_id": payment.payment_id,
                            "order_id": payment.order_id,
                            "user_id": payment.user_id,
                            "amount_paise": payment.amount_paise,
                        },
                    ),
                )
                return payment

        return run_with_retry(_op)

    def mark_event_processed_if_new(self, event_id: str) -> bool:
        def _op() -> bool:
            with connect_payments_db(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO processed_events (event_id) VALUES (?)",
                    (event_id,),
                )
                return cursor.rowcount == 1

        return run_with_retry(_op)
