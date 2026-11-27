"""Resilient HTTP service client with timeouts, circuit breaker, and Zero-Trust token injection."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from shared.resilience.circuit_breaker import CircuitBreaker
from shared.security.tokens import TokenManager


class DownstreamServiceError(RuntimeError):
    """Raised when a downstream service fails with a 5xx or transport failure."""

    def __init__(self, service: str, status_code: int | None, detail: str) -> None:
        self.service = service
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"[{service}] downstream error ({status_code}): {detail}")


class ResilientServiceClient:
    """
    Wraps httpx.AsyncClient for synchronous microservice communication.
    - Attaches short-lived Zero-Trust X-Service-Token automatically.
    - Enforces connect/read/write timeouts.
    - Trips CircuitBreaker ONLY on transport/timeout/5xx faults (never on 4xx domain errors).
    - Retries safe idempotent GET calls once on transient transport failure before tripping.
    """

    def __init__(
        self,
        caller_service: str,
        target_service: str,
        base_url: str,
        token_manager: TokenManager,
        circuit_breaker: CircuitBreaker | None = None,
        timeout_seconds: float = 2.5,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.caller_service = caller_service
        self.target_service = target_service
        self.base_url = base_url.rstrip("/")
        self.token_manager = token_manager
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            name=f"{caller_service}->{target_service}"
        )
        self.timeout = httpx.Timeout(
            connect=min(1.0, timeout_seconds),
            read=timeout_seconds,
            write=timeout_seconds,
            pool=1.0,
        )
        self._transport = transport

    async def request(
        self,
        method: str,
        path: str,
        *,
        user_authorization: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
        timeout_override: float | None = None,
    ) -> httpx.Response:
        req_headers = dict(headers or {})
        req_headers["X-Service-Token"] = self.token_manager.issue_service_token(self.target_service)
        if user_authorization:
            req_headers["Authorization"] = user_authorization

        timeout = (
            httpx.Timeout(
                connect=min(1.0, timeout_override),
                read=timeout_override,
                write=timeout_override,
                pool=1.0,
            )
            if timeout_override is not None
            else self.timeout
        )

        async def _execute() -> httpx.Response:
            max_attempts = 2 if method.upper() == "GET" else 1
            last_exc: Exception | None = None
            total_budget = timeout_override if timeout_override is not None else self.timeout.read
            for attempt in range(max_attempts):
                try:
                    async with httpx.AsyncClient(
                        base_url=self.base_url,
                        timeout=timeout,
                        transport=self._transport,
                    ) as client:
                        coro = client.request(
                            method=method.upper(),
                            url=path,
                            headers=req_headers,
                            params=params,
                            json=json_body,
                        )
                        if total_budget is not None:
                            try:
                                resp = await asyncio.wait_for(coro, timeout=total_budget)
                            except asyncio.TimeoutError as exc:
                                raise httpx.ReadTimeout(
                                    f"[{self.target_service}] exceeded {total_budget:.2f}s timeout budget"
                                ) from exc
                        else:
                            resp = await coro
                    if resp.status_code >= 500:
                        raise DownstreamServiceError(
                            self.target_service,
                            resp.status_code,
                            resp.text[:300],
                        )
                    return resp
                except (httpx.TimeoutException, httpx.TransportError, DownstreamServiceError) as exc:
                    last_exc = exc
                    if attempt + 1 < max_attempts:
                        await asyncio.sleep(0.05)
                        continue
                    raise
            assert last_exc is not None
            raise last_exc

        return await self.circuit_breaker.call(_execute)
