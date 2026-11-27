"""End-to-end Zepto microservices tests: happy path, idempotency, payment failure saga, cancellation."""

from __future__ import annotations

import pytest

from tests.conftest import ZeptoTestMesh


@pytest.mark.anyio
async def test_full_zepto_checkout_and_eventual_consistency(zepto_mesh: ZeptoTestMesh):
    async with zepto_mesh.gateway_client() as client:
        # 1. Authenticate via API Gateway
        auth = await client.post("/api/v1/auth/token", json={"username": "aarav", "pin": "1234"})
        assert auth.status_code == 200
        headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}

        # 2. Check initial stock of prod_milk
        prod_before = (await client.get("/api/v2/catalogues/products/prod_milk")).json()
        initial_stock = prod_before["stock_qty"]

        # 3. Add items to Cart
        add_resp = await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": "prod_milk", "quantity": 2},
        )
        assert add_resp.status_code == 201
        assert add_resp.json()["total_items"] == 2

        # 4. Place Order (idempotent)
        idem_headers = {**headers, "Idempotency-Key": "zepto-order-1"}
        order_resp = await client.post(
            "/api/v1/orders",
            headers=idem_headers,
            json={"delivery_address": "Indiranagar, Bengaluru", "payment_method": "UPI", "payment_token": "aarav@zepto"},
        )
        assert order_resp.status_code == 201
        order = order_resp.json()
        assert order["status"] == "CONFIRMED"
        assert order["total_paise"] == prod_before["pricing"]["selling_paise"] * 2

        # Retry same Idempotency-Key -> same order, stock not double-deducted
        dup_resp = await client.post(
            "/api/v1/orders",
            headers=idem_headers,
            json={"delivery_address": "Indiranagar, Bengaluru", "payment_method": "UPI", "payment_token": "aarav@zepto"},
        )
        assert dup_resp.json()["order_id"] == order["order_id"]

        prod_after = (await client.get("/api/v2/catalogues/products/prod_milk")).json()
        assert prod_after["stock_qty"] == initial_stock - 2

        # 5. Flush Async Event Bus -> Cart cleared & Notifications delivered via Eventual Consistency
        await zepto_mesh.flush_async_events()

        cart_after = (await client.get("/api/v1/cart", headers=headers)).json()
        assert cart_after["total_items"] == 0

        notifs = (await client.get("/api/v1/notifications", headers=headers)).json()
        event_types = {n["event_type"] for n in notifs["items"]}
        assert {"OrderCreated", "PaymentSucceeded", "OrderConfirmed"}.issubset(event_types)


@pytest.mark.anyio
async def test_payment_failure_saga_releases_reserved_stock(zepto_mesh: ZeptoTestMesh):
    async with zepto_mesh.gateway_client() as client:
        auth = await client.post("/api/v1/auth/token", json={"username": "priya", "pin": "5678"})
        headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}

        initial_stock = (await client.get("/api/v2/catalogues/products/prod_bread")).json()["stock_qty"]

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": "prod_bread", "quantity": 3},
        )
        order_resp = await client.post(
            "/api/v1/orders",
            headers={**headers, "Idempotency-Key": "fail-order-1"},
            json={"delivery_address": "Koramangala", "payment_method": "UPI", "payment_token": "decline@upi"},
        )
        assert order_resp.status_code == 201
        order = order_resp.json()
        assert order["status"] == "PAYMENT_FAILED"

        # Flush Async Event Bus -> Catalogues compensates by releasing reserved stock
        await zepto_mesh.flush_async_events()

        stock_after_compensation = (
            await client.get("/api/v2/catalogues/products/prod_bread")
        ).json()["stock_qty"]
        assert stock_after_compensation == initial_stock

        notifs = (await client.get("/api/v1/notifications", headers=headers)).json()
        assert any(n["event_type"] == "PaymentFailed" for n in notifs["items"])


@pytest.mark.anyio
async def test_cancel_confirmed_order_refunds_and_releases_stock(zepto_mesh: ZeptoTestMesh):
    async with zepto_mesh.gateway_client() as client:
        auth = await client.post("/api/v1/auth/token", json={"username": "aarav", "pin": "1234"})
        headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}

        initial_stock = (await client.get("/api/v2/catalogues/products/prod_eggs")).json()["stock_qty"]

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": "prod_eggs", "quantity": 2},
        )
        order = (
            await client.post(
                "/api/v1/orders",
                headers={**headers, "Idempotency-Key": "cancel-order-1"},
                json={"delivery_address": "HSR Layout", "payment_method": "CARD", "payment_token": "visa-4242"},
            )
        ).json()
        assert order["status"] == "CONFIRMED"

        cancel_resp = await client.post(f"/api/v1/orders/{order['order_id']}/cancel", headers=headers)
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "CANCELLED"

        await zepto_mesh.flush_async_events()

        stock_restored = (await client.get("/api/v2/catalogues/products/prod_eggs")).json()["stock_qty"]
        assert stock_restored == initial_stock

        payments = (
            await client.get(f"/api/v1/payments/order/{order['order_id']}", headers=headers)
        ).json()["items"]
        assert payments[0]["status"] == "REFUNDED"
