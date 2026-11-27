"""SQLite repository implementation for Cart."""

from __future__ import annotations

from pathlib import Path

from services.cart.domain.models import Cart, CartItem
from services.cart.domain.repositories import CartRepository
from services.cart.infrastructure.database import connect_cart_db, init_cart_db
from shared.database.sqlite_base import run_with_retry


class SQLiteCartRepository(CartRepository):
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = init_cart_db(db_path)

    def get_cart(self, user_id: str) -> Cart:
        def _op() -> Cart:
            with connect_cart_db(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT product_id, name, unit_label, unit_price_paise, image_emoji, quantity
                    FROM cart_items
                    WHERE user_id = ?
                    ORDER BY name
                    """,
                    (user_id,),
                ).fetchall()
                items = [
                    CartItem(
                        product_id=r["product_id"],
                        name=r["name"],
                        unit_label=r["unit_label"],
                        unit_price_paise=int(r["unit_price_paise"]),
                        image_emoji=r["image_emoji"],
                        quantity=int(r["quantity"]),
                    )
                    for r in rows
                ]
                return Cart(user_id=user_id, items=items)

        return run_with_retry(_op)

    def save_cart(self, cart: Cart) -> None:
        def _op() -> None:
            with connect_cart_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO carts (user_id, updated_at) VALUES (?, datetime('now'))
                    ON CONFLICT(user_id) DO UPDATE SET updated_at = datetime('now')
                    """,
                    (cart.user_id,),
                )
                conn.execute("DELETE FROM cart_items WHERE user_id = ?", (cart.user_id,))
                for item in cart.items:
                    conn.execute(
                        """
                        INSERT INTO cart_items (
                            user_id, product_id, name, unit_label,
                            unit_price_paise, image_emoji, quantity
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            cart.user_id,
                            item.product_id,
                            item.name,
                            item.unit_label,
                            item.unit_price_paise,
                            item.image_emoji,
                            item.quantity,
                        ),
                    )

        run_with_retry(_op)

    def clear_cart(self, user_id: str) -> None:
        def _op() -> None:
            with connect_cart_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))

        run_with_retry(_op)

    def mark_event_processed_if_new(self, event_id: str) -> bool:
        def _op() -> bool:
            with connect_cart_db(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO processed_events (event_id) VALUES (?)",
                    (event_id,),
                )
                return cursor.rowcount == 1

        return run_with_retry(_op)
