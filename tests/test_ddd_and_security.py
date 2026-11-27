"""Tests for DDD invariants, Database-per-Service isolation, Zero-Trust Auth, and Secrets Management."""

from __future__ import annotations

import json
import sqlite3

import httpx
import pytest

from services.cart.domain.models import Cart
from services.catalogues.domain.models import CatalogueItem, InsufficientStockError, Money
from services.orders.domain.models import InvalidOrderTransitionError, Order, OrderItem, OrderStatus
from shared.messaging.event_bus import EventBus
from shared.messaging.events import DomainEvent
from shared.security.secrets import SecretNotFoundError, SecretsManager
from shared.security.tokens import TokenManager
from tests.conftest import ZeptoTestMesh


def test_ddd_domain_invariants():
    item = CatalogueItem("p1", "SKU1", "Milk", "Dairy", "500 ml", Money(2700), Money(3000), 3)
    item.reserve_stock(2)
    assert item.stock_qty == 1
    with pytest.raises(InsufficientStockError):
        item.reserve_stock(2)

    cart = Cart(user_id="u1")
    cart.add_item(
        product_id="p1",
        name="Milk",
        unit_label="500 ml",
        unit_price_paise=2700,
        image_emoji="🥛",
        quantity=2,
    )
    assert cart.total_paise == 5400
    cart.set_quantity("p1", 0)
    assert cart.total_items == 0

    order = Order(
        order_id="ord_1",
        user_id="u1",
        idempotency_key="k1",
        delivery_address="Bengaluru",
        payment_method="UPI",
        items=[OrderItem("p1", "Milk", "500 ml", 2700, 1)],
    )
    assert order.confirm("pay_1") is True
    assert order.confirm("pay_1") is False  # idempotent
    with pytest.raises(InvalidOrderTransitionError):
        order.mark_payment_failed("late")


def test_database_per_service_isolation(zepto_mesh: ZeptoTestMesh):
    expected_dbs = {
        "catalogues.db": {"catalogue_items", "stock_reservations"},
        "cart.db": {"carts", "cart_items"},
        "orders.db": {"orders", "order_items", "outbox_events"},
        "payments.db": {"payments", "outbox_events"},
        "notification.db": {"notifications", "processed_events"},
    }
    for db_name, required_tables in expected_dbs.items():
        db_file = zepto_mesh.data_dir / db_name
        assert db_file.exists()
        with sqlite3.connect(db_file) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert required_tables.issubset(tables)


def test_scoped_secrets_and_key_rotation(tmp_path, monkeypatch):
    vault_path = tmp_path / "vault.json"
    monkeypatch.setenv("ZEPTO_SECRETS_PATH", str(vault_path))
    SecretsManager.ensure_vault(vault_path)

    # Least-privilege secret scoping
    cat_secrets = SecretsManager("catalogues", vault_path)
    with pytest.raises(SecretNotFoundError):
        cat_secrets.get_secret("gateway_demo_users")

    notif_secrets = SecretsManager("notification", vault_path)
    with pytest.raises(SecretNotFoundError):
        notif_secrets.get_secret("service_jwt_active_kid")
    with pytest.raises(SecretNotFoundError):
        notif_secrets.get_secret("gateway_demo_users")

    # Key rotation (kid) preserves active tokens signed with v1 while signing new ones with v2
    gw_secrets = SecretsManager("api-gateway", vault_path)
    gw_tokens = TokenManager(gw_secrets)
    token_v1 = gw_tokens.issue_user_token("usr_1", "Aarav")

    vault_data = json.loads(vault_path.read_text(encoding="utf-8"))
    vault_data["user_jwt_active_kid"] = "user-key-v2"
    vault_path.write_text(json.dumps(vault_data), encoding="utf-8")
    gw_secrets.reload()

    token_v2 = gw_tokens.issue_user_token("usr_1", "Aarav")
    assert gw_tokens.verify_user_token(token_v1).user_id == "usr_1"
    assert gw_tokens.verify_user_token(token_v2).user_id == "usr_1"


@pytest.mark.anyio
async def test_zero_trust_enforcement(zepto_mesh: ZeptoTestMesh):
    # 1. Direct call to Payments without X-Service-Token fails with 401
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=zepto_mesh.payments_app),
        base_url="http://payments.test",
    ) as payments_client:
        resp = await payments_client.get("/api/v1/payments/pay_missing")
        assert resp.status_code == 401

        # 2. Disallowed caller service ('cart' -> 'payments') fails with 403
        cart_tokens = TokenManager(SecretsManager("cart", zepto_mesh.vault_path))
        gw_tokens = TokenManager(SecretsManager("api-gateway", zepto_mesh.vault_path))
        user_jwt = gw_tokens.issue_user_token("usr_aarav", "Aarav")
        resp = await payments_client.get(
            "/api/v1/payments/pay_missing",
            headers={
                "X-Service-Token": cart_tokens.issue_service_token("payments"),
                "Authorization": f"Bearer {user_jwt}",
            },
        )
        assert resp.status_code == 403

    # 3. 'cart' cannot call 'catalogues' POST /reservations (orders only -> 403)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=zepto_mesh.catalogues_app),
        base_url="http://catalogues.test",
    ) as cat_client:
        cart_tokens = TokenManager(SecretsManager("cart", zepto_mesh.vault_path))
        resp = await cat_client.post(
            "/api/v1/catalogues/reservations",
            headers={"X-Service-Token": cart_tokens.issue_service_token("catalogues")},
            json={"order_id": "ord_hack", "items": [{"product_id": "prod_milk", "quantity": 1}]},
        )
        assert resp.status_code == 403

    # 4. Tampered event signature is rejected on EventBus and recorded in DLQ
    bus = EventBus("orders", zepto_mesh.data_dir / "event_bus.db")
    tampered = DomainEvent(
        event_type="OrderCreated",
        producer="rogue",
        payload={"order_id": "ord_bad", "user_id": "usr_aarav"},
        signature="deadbeef",
    )
    with bus._connect() as conn:
        conn.execute(
            """
            INSERT INTO bus_events (
                event_id, topic, event_type, schema_version,
                producer, correlation_id, occurred_at, payload_json, signature
            ) VALUES (?, 'orders.events', 'OrderCreated', '1.0', 'rogue', '', '2026-01-01', '{}', ?)
            """,
            (tampered.event_id, tampered.signature),
        )
    await zepto_mesh.cart_app.state.event_bus.process_once(
        "cart-group", zepto_mesh.cart_app.state.event_handlers
    )
    with bus._connect() as conn:
        dlq = conn.execute(
            "SELECT error FROM dead_letter_events WHERE event_id = ?",
            (tampered.event_id,),
        ).fetchone()
    assert dlq is not None
    assert "signature" in dlq["error"].lower()
