"""FastAPI Zero-Trust enforcement dependencies for microservice endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fastapi import Header, HTTPException, status

from shared.security.secrets import SecretsManager
from shared.security.tokens import ServiceClaims, TokenManager, TokenValidationError, UserClaims


@dataclass(frozen=True)
class ZeroTrustContext:
    user: UserClaims
    service: ServiceClaims


def build_zero_trust_dependencies(
    service_name: str,
    allowed_callers: set[str],
) -> tuple[Callable[..., ServiceClaims], Callable[..., ZeroTrustContext]]:
    """
    Creates FastAPI dependencies enforcing:
    1. Valid cryptographic X-Service-Token targeted at `service_name`
    2. Caller service explicitly present in `allowed_callers` (Zero-Trust least privilege)
    3. Valid cryptographic Authorization: Bearer <user_jwt>
    """
    secrets_mgr = SecretsManager(service_name)
    token_mgr = TokenManager(secrets_mgr)

    def require_service_auth(
        x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
    ) -> ServiceClaims:
        if not x_service_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Zero-Trust enforcement: missing X-Service-Token",
            )
        try:
            svc_claims = token_mgr.verify_service_token(x_service_token, service_name)
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Zero-Trust enforcement: {exc}",
            ) from exc

        if svc_claims.caller_service not in allowed_callers:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Zero-Trust policy denied caller '{svc_claims.caller_service}' "
                    f"for target '{service_name}'"
                ),
            )
        return svc_claims

    def require_zero_trust_user(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_service_token: str | None = Header(default=None, alias="X-Service-Token"),
    ) -> ZeroTrustContext:
        svc_claims = require_service_auth(x_service_token)
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or malformed Bearer user token",
            )
        raw_user_token = authorization.split(" ", 1)[1].strip()
        try:
            user_claims = token_mgr.verify_user_token(raw_user_token)
        except TokenValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid user token: {exc}",
            ) from exc
        return ZeroTrustContext(user=user_claims, service=svc_claims)

    return require_service_auth, require_zero_trust_user
