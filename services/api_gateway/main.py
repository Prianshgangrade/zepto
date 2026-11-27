"""API Gateway FastAPI app: Auth token issuance, versioned routing, Circuit Breakers & Graceful Degradation."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from services.api_gateway.config import (
    GatewayServiceRegistry,
    build_gateway_clients,
    create_gateway_security,
)
from shared.resilience.circuit_breaker import CircuitBreakerOpenError
from shared.resilience.http_client import DownstreamServiceError, ResilientServiceClient
from shared.security.secrets import SecretsManager
from shared.security.tokens import TokenValidationError, UserClaims
from shared.versioning.headers import APIVersioningMiddleware


class TokenIssueRequest(BaseModel):
    username: str = Field(min_length=2)
    pin: str = Field(min_length=4, max_length=16)


class TTLCache:
    """Bounded TTL cache supporting Graceful Degradation on downstream outages."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self.ttl_seconds = ttl_seconds
        self._store: dict[str, tuple[float, dict[str, Any]]] = {}

    def set(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = (time.monotonic(), value)

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        saved_at, value = entry
        if time.monotonic() - saved_at > self.ttl_seconds:
            return None
        return value


FORWARDED_HEADERS = ("idempotency-key", "x-simulate-delay-ms")
UPSTREAM_RESPONSE_HEADERS = ("x-api-version", "deprecation", "link")


def _extract_forward_headers(request: Request) -> dict[str, str]:
    return {
        k: v
        for k in FORWARDED_HEADERS
        if (v := request.headers.get(k)) is not None
    }


def _relay_response(upstream: httpx.Response) -> Response:
    headers = {
        k: v
        for k in UPSTREAM_RESPONSE_HEADERS
        if (v := upstream.headers.get(k)) is not None
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type", "application/json"),
        headers=headers,
    )


def create_api_gateway_app(
    *,
    transports: dict[str, httpx.AsyncBaseTransport] | None = None,
    vault_path: Path | None = None,
    timeout_seconds: float | None = None,
) -> FastAPI:
    if vault_path is not None:
        SecretsManager.ensure_vault(vault_path)
    secrets_mgr, token_mgr = create_gateway_security()
    if vault_path is not None:
        secrets_mgr.vault_path = vault_path
        secrets_mgr.reload()

    registry = build_gateway_clients(
        token_mgr,
        transports=transports,
        timeout_seconds=timeout_seconds,
    )
    catalogue_cache = TTLCache(ttl_seconds=300.0)

    def require_gateway_user(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> tuple[UserClaims, str]:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Bearer token",
            )
        raw_token = authorization.split(" ", 1)[1].strip()
        try:
            claims = token_mgr.verify_user_token(raw_token)
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
        return claims, authorization

    app = FastAPI(title="Zepto API Gateway", version="1.0.0")
    app.add_middleware(APIVersioningMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-API-Version", "X-Degraded", "Deprecation", "Link"],
    )

    app.state.registry = registry
    app.state.catalogue_cache = catalogue_cache
    app.state.token_manager = token_mgr

    @app.get("/health")
    def health() -> dict:
        breakers = {
            name: {
                "state": client.circuit_breaker.snapshot().state.value,
                "failure_count": client.circuit_breaker.snapshot().failure_count,
                "opened_count": client.circuit_breaker.snapshot().opened_count,
            }
            for name, client in registry.all_clients().items()
        }
        return {"service": "api-gateway", "status": "ok", "circuit_breakers": breakers}

    @app.post("/api/v1/auth/token")
    def issue_token(body: TokenIssueRequest) -> dict:
        users = secrets_mgr.get_secret("gateway_demo_users")
        record = users.get(body.username.strip().lower())
        if not record or not SecretsManager.verify_pin(body.pin, record["pin_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or PIN",
            )
        token = token_mgr.issue_user_token(
            user_id=record["user_id"],
            name=record["name"],
            role=record["role"],
        )
        return {
            "access_token": token,
            "token_type": "bearer",
            "expires_in": 3600,
            "user": {
                "user_id": record["user_id"],
                "name": record["name"],
                "role": record["role"],
            },
        }

    async def _proxy(
        client: ResilientServiceClient,
        request: Request,
        target_path: str,
        user_auth: str | None = None,
    ) -> Response:
        raw_body = await request.body()
        json_body = None
        if raw_body:
            try:
                json_body = await request.json()
            except Exception as exc:
                raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc

        resp = await client.request(
            request.method,
            target_path,
            user_authorization=user_auth,
            headers=_extract_forward_headers(request),
            params=dict(request.query_params),
            json_body=json_body,
        )
        return _relay_response(resp)

    @app.get("/api/{version}/catalogues/{subpath:path}")
    async def proxy_catalogues_get(version: str, subpath: str, request: Request):
        if version not in ("v1", "v2"):
            raise HTTPException(status_code=404, detail=f"Unsupported API version '{version}'")
        target_path = f"/api/{version}/catalogues/{subpath}"
        cache_key = f"{target_path}?{request.url.query}"
        try:
            resp = await _proxy(registry.catalogues, request, target_path)
            if resp.status_code == 200 and subpath.startswith("products"):
                catalogue_cache.set(cache_key, await _parse_json_bytes(resp.body))
            return resp
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ):
            cached = catalogue_cache.get(cache_key)
            if cached is not None:
                degraded_payload = dict(cached)
                degraded_payload["degraded"] = True
                degraded_payload["degraded_reason"] = (
                    "Catalogues service unavailable; serving cached response from API Gateway"
                )
                return JSONResponse(
                    status_code=200,
                    content=degraded_payload,
                    headers={"X-Degraded": "true", "X-API-Version": version},
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Catalogues service unavailable and no cached data available",
            )

    @app.api_route("/api/v1/cart", methods=["GET", "DELETE"])
    @app.api_route("/api/v1/cart/{subpath:path}", methods=["GET", "POST", "PATCH", "DELETE"])
    async def proxy_cart(
        request: Request,
        subpath: str = "",
        auth: tuple[UserClaims, str] = Depends(require_gateway_user),
    ):
        target_path = f"/api/v1/cart/{subpath}" if subpath else "/api/v1/cart"
        try:
            return await _proxy(registry.cart, request, target_path, user_auth=auth[1])
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Cart service temporarily unavailable: {exc}",
            )

    @app.api_route("/api/v1/orders", methods=["GET", "POST"])
    @app.api_route("/api/v1/orders/{subpath:path}", methods=["GET", "POST"])
    async def proxy_orders(
        request: Request,
        subpath: str = "",
        auth: tuple[UserClaims, str] = Depends(require_gateway_user),
    ):
        target_path = f"/api/v1/orders/{subpath}" if subpath else "/api/v1/orders"
        try:
            return await _proxy(registry.orders, request, target_path, user_auth=auth[1])
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Orders service temporarily unavailable: {exc}",
            )

    @app.get("/api/v1/payments/{subpath:path}")
    async def proxy_payments_read(
        subpath: str,
        request: Request,
        auth: tuple[UserClaims, str] = Depends(require_gateway_user),
    ):
        try:
            return await _proxy(
                registry.payments,
                request,
                f"/api/v1/payments/{subpath}",
                user_auth=auth[1],
            )
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Payments service temporarily unavailable: {exc}",
            )

    @app.api_route("/api/v1/notifications", methods=["GET"])
    @app.api_route("/api/v1/notifications/{subpath:path}", methods=["POST"])
    async def proxy_notifications(
        request: Request,
        subpath: str = "",
        auth: tuple[UserClaims, str] = Depends(require_gateway_user),
    ):
        target_path = (
            f"/api/v1/notifications/{subpath}" if subpath else "/api/v1/notifications"
        )
        try:
            return await _proxy(registry.notification, request, target_path, user_auth=auth[1])
        except (
            CircuitBreakerOpenError,
            DownstreamServiceError,
            httpx.TimeoutException,
            httpx.TransportError,
        ):
            if request.method == "GET":
                return JSONResponse(
                    status_code=200,
                    content={
                        "api_version": "v1",
                        "degraded": True,
                        "degraded_reason": "Notification service temporarily unavailable",
                        "unread_count": 0,
                        "items": [],
                    },
                    headers={"X-Degraded": "true", "X-API-Version": "v1"},
                )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Notification service temporarily unavailable",
            )

    return app


async def _parse_json_bytes(raw: bytes) -> dict[str, Any]:
    import json

    return json.loads(raw.decode("utf-8"))


app = create_api_gateway_app()
