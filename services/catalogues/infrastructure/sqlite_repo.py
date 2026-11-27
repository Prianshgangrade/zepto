"""SQLite repository implementation for Catalogues."""

from __future__ import annotations

from pathlib import Path
import sqlite3

from services.catalogues.domain.models import (
    CatalogueItem,
    Money,
    ProductNotFoundError,
    ReservedLineItem,
    StockReservationRequestItem,
)
from services.catalogues.domain.repositories import CatalogueRepository
from services.catalogues.infrastructure.database import connect_catalogues_db, init_catalogues_db
from shared.database.sqlite_base import run_with_retry


class SQLiteCatalogueRepository(CatalogueRepository):
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = init_catalogues_db(db_path)

    def _row_to_item(self, row: sqlite3.Row) -> CatalogueItem:
        return CatalogueItem(
            product_id=row["product_id"],
            sku=row["sku"],
            name=row["name"],
            category=row["category"],
            unit_label=row["unit_label"],
            price=Money(int(row["price_paise"])),
            mrp=Money(int(row["mrp_paise"])),
            stock_qty=int(row["stock_qty"]),
            eta_minutes=int(row["eta_minutes"]),
            image_emoji=row["image_emoji"],
        )

    def seed_if_empty(self, items: list[CatalogueItem]) -> None:
        def _op() -> None:
            with connect_catalogues_db(self.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) AS cnt FROM catalogue_items").fetchone()["cnt"]
                if count > 0:
                    return
                for item in items:
                    conn.execute(
                        """
                        INSERT INTO catalogue_items (
                            product_id, sku, name, category, unit_label,
                            price_paise, mrp_paise, stock_qty, eta_minutes, image_emoji
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.product_id,
                            item.sku,
                            item.name,
                            item.category,
                            item.unit_label,
                            item.price.paise,
                            item.mrp.paise,
                            item.stock_qty,
                            item.eta_minutes,
                            item.image_emoji,
                        ),
                    )

        run_with_retry(_op)

    def list_items(self, category: str | None = None, search: str | None = None) -> list[CatalogueItem]:
        def _op() -> list[CatalogueItem]:
            clauses: list[str] = []
            params: list[str] = []
            if category and category.lower() != "all":
                clauses.append("LOWER(category) = LOWER(?)")
                params.append(category.strip())
            if search:
                clauses.append("(LOWER(name) LIKE ? OR LOWER(category) LIKE ?)")
                pattern = f"%{search.strip().lower()}%"
                params.extend([pattern, pattern])
            where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            with connect_catalogues_db(self.db_path) as conn:
                rows = conn.execute(
                    f"SELECT * FROM catalogue_items {where_sql} ORDER BY category, name",
                    params,
                ).fetchall()
                return [self._row_to_item(r) for r in rows]

        return run_with_retry(_op)

    def get_item(self, product_id: str) -> CatalogueItem | None:
        def _op() -> CatalogueItem | None:
            with connect_catalogues_db(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM catalogue_items WHERE product_id = ?",
                    (product_id,),
                ).fetchone()
                return self._row_to_item(row) if row else None

        return run_with_retry(_op)

    def reserve_for_order(
        self,
        order_id: str,
        items: list[StockReservationRequestItem],
    ) -> list[ReservedLineItem]:
        def _op() -> list[ReservedLineItem]:
            with connect_catalogues_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                existing = conn.execute(
                    """
                    SELECT r.product_id, r.quantity, r.unit_price_paise,
                           c.name, c.unit_label, c.image_emoji
                    FROM stock_reservations r
                    JOIN catalogue_items c ON c.product_id = r.product_id
                    WHERE r.order_id = ?
                    """,
                    (order_id,),
                ).fetchall()
                if existing:
                    return [
                        ReservedLineItem(
                            product_id=row["product_id"],
                            name=row["name"],
                            unit_label=row["unit_label"],
                            unit_price_paise=int(row["unit_price_paise"]),
                            quantity=int(row["quantity"]),
                            image_emoji=row["image_emoji"],
                        )
                        for row in existing
                    ]

                reserved: list[ReservedLineItem] = []
                for req in items:
                    row = conn.execute(
                        "SELECT * FROM catalogue_items WHERE product_id = ?",
                        (req.product_id,),
                    ).fetchone()
                    if row is None:
                        raise ProductNotFoundError(f"Product '{req.product_id}' not found")
                    item = self._row_to_item(row)
                    item.reserve_stock(req.quantity)
                    conn.execute(
                        "UPDATE catalogue_items SET stock_qty = ? WHERE product_id = ?",
                        (item.stock_qty, item.product_id),
                    )
                    conn.execute(
                        """
                        INSERT INTO stock_reservations (
                            order_id, product_id, quantity, unit_price_paise, status
                        ) VALUES (?, ?, ?, ?, 'RESERVED')
                        """,
                        (order_id, item.product_id, req.quantity, item.price.paise),
                    )
                    reserved.append(
                        ReservedLineItem(
                            product_id=item.product_id,
                            name=item.name,
                            unit_label=item.unit_label,
                            unit_price_paise=item.price.paise,
                            quantity=req.quantity,
                            image_emoji=item.image_emoji,
                        )
                    )
                return reserved

        return run_with_retry(_op)

    def release_for_order(self, order_id: str) -> int:
        def _op() -> int:
            with connect_catalogues_db(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT product_id, quantity
                    FROM stock_reservations
                    WHERE order_id = ? AND status = 'RESERVED'
                    """,
                    (order_id,),
                ).fetchall()
                if not rows:
                    return 0
                for row in rows:
                    conn.execute(
                        "UPDATE catalogue_items SET stock_qty = stock_qty + ? WHERE product_id = ?",
                        (int(row["quantity"]), row["product_id"]),
                    )
                conn.execute(
                    "UPDATE stock_reservations SET status = 'RELEASED' WHERE order_id = ? AND status = 'RESERVED'",
                    (order_id,),
                )
                return len(rows)

        return run_with_retry(_op)

    def mark_event_processed_if_new(self, event_id: str) -> bool:
        def _op() -> bool:
            with connect_catalogues_db(self.db_path) as conn:
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO processed_events (event_id) VALUES (?)",
                    (event_id,),
                )
                return cursor.rowcount == 1

        return run_with_retry(_op)
