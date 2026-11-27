"""Tests for Circuit Breakers, Timeouts, and Graceful Degradation."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from shared.resilience.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    CircuitState,
)
from tests.conftest import ZeptoTestMesh, build_test_mesh


@pytest.mark.anyio
async def test_circuit_breaker_state_transitions():
    now = [0.0]
    cb = CircuitBreaker(
        name="test-cb",
        failure_threshold=2,
        recovery_timeout_seconds=10.0,
        clock=lambda: now[0],
    )

    async def fail_fn():
        raise RuntimeError("boom")

    async def ok_fn():
        return "ok"

    for _ in range(2):
        with pytest.raises(RuntimeError):
            await cb.call(fail_fn)

    assert cb.snapshot().state == CircuitState.OPEN
    with pytest.raises(CircuitBreakerOpenError):
        await cb.call(ok_fn)

    # Advance past recovery timeout -> HALF_OPEN probe succeeds -> CLOSED
    now[0] = 11.0
    assert cb.snapshot().state == CircuitState.HALF_OPEN
    assert await cb.call(ok_fn) == "ok"
    assert cb.snapshot().state == CircuitState.CLOSED


@pytest.mark.anyio
async def test_gateway_graceful_degradation_catalogues_and_notifications(tmp_path, monkeypatch):
    # First warm up gateway cache when Catalogues is healthy, then simulate 503 outage
    catalogues_up = [True]
    notifications_up = [True]

    mesh = build_test_mesh(tmp_path, monkeypatch, timeout_seconds=1.0)
    real_cat_transport = httpx.ASGITransport(app=mesh.catalogues_app)
    real_notif_transport = httpx.ASGITransport(app=mesh.notification_app)

    async def cat_handler(request: httpx.Request) -> httpx.Response:
        if not catalogues_up[0]:
            return httpx.Response(503, json={"detail": "down"})
        return await real_cat_transport.handle_async_request(request)

    async def notif_handler(request: httpx.Request) -> httpx.Response:
        if not notifications_up[0]:
            return httpx.Response(503, json={"detail": "down"})
        return await real_notif_transport.handle_async_request(request)

    mesh.gateway_app.state.registry.catalogues._transport = httpx.MockTransport(cat_handler)
    mesh.gateway_app.state.registry.notification._transport = httpx.MockTransport(notif_handler)

    async with mesh.gateway_client() as client:
        token_resp = await client.post("/api/v1/auth/token", json={"username": "aarav", "pin": "1234"})
        jwt_token = token_resp.json()["access_token"]
        auth_headers = {"Authorization": f"Bearer {jwt_token}"}

        # Warm catalogue cache
        ok_res = await client.get("/api/v2/catalogues/products")
        assert ok_res.status_code == 200
        assert ok_res.json()["degraded"] is False

        # Break catalogues -> Gateway degrades gracefully using cache!
        catalogues_up[0] = False
        degraded_res = await client.get("/api/v2/catalogues/products")
        assert degraded_res.status_code == 200
        assert degraded_res.headers.get("X-Degraded") == "true"
        assert degraded_res.json()["degraded"] is True
        assert len(degraded_res.json()["items"]) > 0

        # Break notification -> Gateway degrades gracefully with empty list!
        notifications_up[0] = False
        notif_res = await client.get("/api/v1/notifications", headers=auth_headers)
        assert notif_res.status_code == 200
        assert notif_res.json()["degraded"] is True
        assert notif_res.json()["items"] == []


@pytest.mark.anyio
async def test_orders_graceful_degradation_on_payment_timeout(tmp_path, monkeypatch):
    # Inner timeout 0.15s -> X-Simulate-Delay-Ms: 400 trips Orders->Payments timeout
    mesh = build_test_mesh(tmp_path, monkeypatch, timeout_seconds=0.15)
    mesh.gateway_app.state.registry.orders.timeout = httpx.Timeout(connect=1.0, read=2.5, write=2.5, pool=1.0)

    async with mesh.gateway_client() as client:
        token = (await client.post("/api/v1/auth/token", json={"username": "aarav", "pin": "1234"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": "prod_milk", "quantity": 1},
        )

        # Simulate slow Payments service exceeding Orders' 0.15s timeout
        order_resp = await client.post(
            "/api/v1/orders",
            headers={**headers, "Idempotency-Key": "timeout-test-1", "X-Simulate-Delay-Ms": "400"},
            json={"delivery_address": "Indiranagar", "payment_method": "UPI", "payment_token": "zepto@upi"},
        )
        assert order_resp.status_code == 202
        body = order_resp.json()
        assert body["status"] == "PAYMENT_PENDING"
        assert body["degraded"] is True

        # Retry payment normally -> converges to CONFIRMED
        retry_resp = await client.post(
            f"/api/v1/orders/{body['order_id']}/retry-payment",
            headers=headers,
            json={"payment_method": "UPI", "payment_token": "zepto@upi"},
        )
        assert retry_resp.status_code == 200
        assert retry_resp.json()["status"] == "CONFIRMED"


@pytest.mark.anyio
async def test_cart_graceful_degradation_when_catalogues_down(tmp_path, monkeypatch):
    catalogues_up = [True]
    mesh = build_test_mesh(tmp_path, monkeypatch, timeout_seconds=1.0)
    real_cat_transport = httpx.ASGITransport(app=mesh.catalogues_app)

    async def cat_handler(request: httpx.Request) -> httpx.Response:
        if not catalogues_up[0]:
            return httpx.Response(503, json={"detail": "down"})
        return await real_cat_transport.handle_async_request(request)

    mesh.cart_app.state.catalogues_client.client._transport = httpx.MockTransport(cat_handler)

    async with mesh.gateway_client() as client:
        token = (await client.post("/api/v1/auth/token", json={"username": "aarav", "pin": "1234"})).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        add_res = await client.post(
            "/api/v1/cart/items",
            headers=headers,
            json={"product_id": "prod_milk", "quantity": 1},
        )
        assert add_res.status_code == 201

        # Catalogues goes down -> Cart serves locally cached product snapshot gracefully
        catalogues_up[0] = False
        cart_res = await client.get("/api/v1/cart", headers=headers)
        assert cart_res.status_code == 200
        assert cart_res.json()["degraded"] is True
        assert cart_res.json()["items"][0]["product_id"] == "prod_milk"
