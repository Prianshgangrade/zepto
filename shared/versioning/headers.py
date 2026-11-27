"""Middleware adding explicit API version headers and v1 deprecation hints."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class APIVersioningMiddleware(BaseHTTPMiddleware):
    """Emits X-API-Version and optional Deprecation metadata on versioned routes."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/api/v2/"):
            response.headers["X-API-Version"] = "v2"
        elif path.startswith("/api/v1/"):
            response.headers["X-API-Version"] = "v1"
            if path.startswith("/api/v1/catalogues"):
                response.headers["Deprecation"] = "true"
                response.headers["Link"] = '</api/v2/catalogues/products>; rel="successor-version"'
        return response
