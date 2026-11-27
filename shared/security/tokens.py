"""JWT issuance and verification for both End-User and Service-to-Service Zero-Trust tokens."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import jwt

from shared.security.secrets import SecretsManager


USER_ISSUER = "zepto-api-gateway"
USER_AUDIENCE = "zepto-services"
SERVICE_AUDIENCE_PREFIX = "service:"


class TokenValidationError(Exception):
    """Raised when a user or service token fails cryptographic or policy validation."""


@dataclass(frozen=True)
class UserClaims:
    user_id: str
    name: str
    role: str
    jti: str


@dataclass(frozen=True)
class ServiceClaims:
    caller_service: str
    target_service: str
    jti: str


class TokenManager:
    """Issues and verifies short-lived HS256 JWTs with key-id (kid) rotation support."""

    def __init__(self, secrets_manager: SecretsManager) -> None:
        self.secrets = secrets_manager

    def issue_user_token(
        self,
        user_id: str,
        name: str,
        role: str = "customer",
        ttl_seconds: int = 3600,
    ) -> str:
        kid = self.secrets.get_secret("user_jwt_active_kid")
        keys = self.secrets.get_secret("user_jwt_keys")
        signing_key = keys[kid]
        now = int(time.time())
        payload = {
            "iss": USER_ISSUER,
            "aud": USER_AUDIENCE,
            "sub": user_id,
            "name": name,
            "role": role,
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl_seconds,
        }
        return jwt.encode(payload, signing_key, algorithm="HS256", headers={"kid": kid})

    def verify_user_token(self, token: str) -> UserClaims:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            keys: dict[str, str] = self.secrets.get_secret("user_jwt_keys")
            if not kid or kid not in keys:
                raise TokenValidationError("Unknown or missing user token key id (kid)")
            decoded: dict[str, Any] = jwt.decode(
                token,
                keys[kid],
                algorithms=["HS256"],
                audience=USER_AUDIENCE,
                issuer=USER_ISSUER,
            )
            return UserClaims(
                user_id=str(decoded["sub"]),
                name=str(decoded.get("name", "")),
                role=str(decoded.get("role", "customer")),
                jti=str(decoded["jti"]),
            )
        except jwt.PyJWTError as exc:
            raise TokenValidationError(f"Invalid user token: {exc}") from exc

    def issue_service_token(self, target_service: str, ttl_seconds: int = 60) -> str:
        kid = self.secrets.get_secret("service_jwt_active_kid")
        keys = self.secrets.get_secret("service_jwt_keys")
        signing_key = keys[kid]
        now = int(time.time())
        payload = {
            "iss": self.secrets.service_name,
            "aud": f"{SERVICE_AUDIENCE_PREFIX}{target_service}",
            "sub": f"svc:{self.secrets.service_name}",
            "jti": str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl_seconds,
        }
        return jwt.encode(payload, signing_key, algorithm="HS256", headers={"kid": kid})

    def verify_service_token(self, token: str, expected_target_service: str) -> ServiceClaims:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            keys: dict[str, str] = self.secrets.get_secret("service_jwt_keys")
            if not kid or kid not in keys:
                raise TokenValidationError("Unknown or missing service token key id (kid)")
            decoded: dict[str, Any] = jwt.decode(
                token,
                keys[kid],
                algorithms=["HS256"],
                audience=f"{SERVICE_AUDIENCE_PREFIX}{expected_target_service}",
            )
            return ServiceClaims(
                caller_service=str(decoded["iss"]),
                target_service=expected_target_service,
                jti=str(decoded["jti"]),
            )
        except jwt.PyJWTError as exc:
            raise TokenValidationError(f"Invalid service token: {exc}") from exc
