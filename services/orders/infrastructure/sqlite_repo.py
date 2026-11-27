"""SQLite repository + Transactional Outbox for Orders."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from services.orders.domain.models import Order, OrderItem, OrderStatus
from services.orders.domain.repositories import OrderRepository
from services.orders.infrastructure.database import connect_orders_db, init_orders_db
from shared.database.sqlite_base import run_with_retry
from shared.messaging.events import DomainEvent
from shared.messaging.outbox import enqueue_outbox_event


class SQLiteOrderRepository(OrderRepository):
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = init_orders_db(db_path)

    @staticmethod
    def _load_order(conn: sqlite3.Connection, row: sqlite3.Row) -> Order:
        item_rows = conn.execute(
            """
            SELECT product_id, name, unit_label, unit_price_paise, quantity, image_emoji
            FROM order_items
            WHERE order_id = ?
            ORDER BY id ASC
            """,
            (row["order_id"],),
        ).fetchall()
        items = [
            OrderItem(
                product_id=ir["product_id"],
                name=ir["name"],
                unit_label=ir["unit_label"],
                unit_price_paise=int(ir["unit_price_paise"]),
                quantity=int(ir["quantity"]),
                image_emoji=ir["image_emoji"],
            )
            for ir in item_rows
        ]
        return Order(
            order_id=row["order_id"],
            user_id=row["user_id"],
            idempotency_key=row["idempotency_key"],
            delivery_address=row["delivery_address"],
            payment_method=row["payment_method"],
            items=items,
            status=OrderStatus(row["status"]),
            payment_id=row["payment_id"],
            failure_reason=row["failure_reason"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def get_by_idempotency_key(self, user_id: str, idempotency_key: str) -> Order | None:
        def _op() -> Order | None:
            with connect_orders_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM orders WHERE user_id = ? AND idempotency_key = ?",
                    (user_id, idempotency_key),
                ).fetchone()
                return self._load_order(conn, row) if row else None

        return run_with_retry(_op)

    def get_by_id(self, order_id: str) -> Order | None:
        def _op() -> Order | None:
            with connect_orders_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM orders WHERE order_id = ?",
                    (order_id,),
                ).fetchone()
                return self._load_order(conn, row) if row else None

        return run_with_retry(_op)

    def list_for_user(self, user_id: str) -> list[Order]:
        def _op() -> list[Order]:
            with connect_orders_db(self.db_path) as conn:
                rows = conn.execute(
                    "SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,),
                ).fetchall()
                return [self._load_order(conn, r) for r in rows]

        return run_with_retry(_op)

    def create_with_outbox(self, order: Order) -> None:
        event = DomainEvent(
            event_type="OrderCreated",
            producer="orders",
            correlation_id=order.order_id,
            payload={
                "order_id": order.order_id,
                "user_id": order.user_id,
                "total_paise": order.total_paise,
                "payment_method": order.payment_method,
                "items": [
                    {"product_id": i.product_id, "quantity": i.quantity}
                    for i in order.items
                ],
            },
        )

        def _op() -> None:
            with connect_orders_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO orders (
                        order_id, user_id, idempotency_key, delivery_address,
                        payment_method, status, payment_id, failure_reason,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        order.order_id,
                        order.user_id,
                        order.idempotency_key,
                        order.delivery_address,
                        order.payment_method,
                        order.status.value,
                        order.payment_id,
                        order.failure_reason,
                        order.created_at,
                        order.updated_at,
                    ),
                )
                for item in order.items:
                    conn.execute(
                        """
                        INSERT INTO order_items (
                            order_id, product_id, name, unit_label,
                            unit_price_paise, quantity, image_emoji
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            order.order_id,
                            item.product_id,
                            item.name,
                            item.unit_label,
                            item.unit_price_paise,
                            item.quantity,
                            item.image_emoji,
                        ),
                    )
                enqueue_outbox_event(conn, "orders.events", event)

        run_with_retry(_op)

    def update_with_outbox(self, order: Order, event_type: str | None = None) -> None:
        def _op() -> None:
            with connect_orders_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE orders
                    SET status = ?, payment_id = ?, failure_reason = ?, updated_at = ?
                    WHERE order_id = ?
                    """,
                    (
                        order.status.value,
                        order.payment_id,
                        order.failure_reason,
                        order.updated_at,
                        order.order_id,
                    ),
                )
                if event_type:
                    enqueue_outbox_event(
                        conn,
                        "orders.events",
                        DomainEvent(
                            event_type=event_type,
                            producer="orders",
                            correlation_id=order.order_id,
                            payload={
                                "order_id": order.order_id,
                                "user_id": order.user_id,
                                "status": order.status.value,
                                "payment_id": order.payment_id,
                                "total_paise": order.total_paise,
                                "failure_reason": order.failure_reason,
                            },
                        ),
                    )

        run_with_retry(_op)

    def mark_event_processed_if_new(self, event_id: str) -> bool:
        def _op() -> bool:
            with connect_orders_db(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO processed_events (event_id) VALUES (?)",
                    (event_id,),
                )
                return cursor.rowcount == 1

        return run_with_retry(_op)
