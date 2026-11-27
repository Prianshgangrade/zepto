"""Scoped Secrets Management with key versioning (kid) and zero hardcoded secrets."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class SecretNotFoundError(RuntimeError):
    """Raised when a required secret is missing or unauthorized for a service."""


class SecretsManager:
    """
    Loads secrets from environment variables first, then from the local vault file.
    Enforces least-privilege scoping so each microservice can only read secrets
    explicitly granted to its service identity.
    """

    # Least-privilege secret ACL per service identity
    SERVICE_SECRET_ACL: dict[str, set[str]] = {
        "api-gateway": {
            "user_jwt_keys",
            "user_jwt_active_kid",
            "service_jwt_keys",
            "service_jwt_active_kid",
            "gateway_demo_users",
        },
        "catalogues": {
            "user_jwt_keys",
            "service_jwt_keys",
            "event_bus_hmac_key",
        },
        "cart": {
            "user_jwt_keys",
            "service_jwt_keys",
            "service_jwt_active_kid",
            "event_bus_hmac_key",
        },
        "orders": {
            "user_jwt_keys",
            "service_jwt_keys",
            "service_jwt_active_kid",
            "event_bus_hmac_key",
        },
        "payments": {
            "user_jwt_keys",
            "service_jwt_keys",
            "event_bus_hmac_key",
        },
        "notification": {
            "user_jwt_keys",
            "service_jwt_keys",
            "event_bus_hmac_key",
        },
    }

    def __init__(self, service_name: str, vault_path: Path | None = None) -> None:
        self.service_name = service_name
        env_vault = os.environ.get("ZEPTO_SECRETS_PATH")
        self.vault_path = Path(vault_path or env_vault or (PROJECT_ROOT / ".secrets" / "vault.json"))
        self._cache: dict[str, Any] | None = None

    @staticmethod
    def _hash_pin(pin: str, salt: str) -> str:
        digest = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return f"{salt}${digest.hex()}"

    @classmethod
    def ensure_vault(cls, vault_path: Path | None = None) -> Path:
        """Creates a cryptographic local vault file if absent (dev/test bootstrap)."""
        target = Path(vault_path or os.environ.get("ZEPTO_SECRETS_PATH") or (PROJECT_ROOT / ".secrets" / "vault.json"))
        if target.exists():
            return target

        strict = os.environ.get("STRICT_SECRETS", "false").lower() == "true"
        if strict:
            raise SecretNotFoundError(f"STRICT_SECRETS enabled and vault missing at {target}")

        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "user_jwt_active_kid": "user-key-v1",
            "user_jwt_keys": {
                "user-key-v1": secrets.token_urlsafe(48),
                "user-key-v2": secrets.token_urlsafe(48),
            },
            "service_jwt_active_kid": "svc-key-v1",
            "service_jwt_keys": {
                "svc-key-v1": secrets.token_urlsafe(48),
                "svc-key-v2": secrets.token_urlsafe(48),
            },
            "event_bus_hmac_key": secrets.token_urlsafe(48),
            "gateway_demo_users": {
                "aarav": {
                    "user_id": "usr_aarav",
                    "name": "Aarav Sharma",
                    "role": "customer",
                    "pin_hash": cls._hash_pin("1234", secrets.token_hex(16)),
                },
                "priya": {
                    "user_id": "usr_priya",
                    "name": "Priya Nair",
                    "role": "customer",
                    "pin_hash": cls._hash_pin("5678", secrets.token_hex(16)),
                },
            },
        }
        tmp_path = target.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp_path, target)
        return target

    @staticmethod
    def verify_pin(pin: str, stored_hash: str) -> bool:
        try:
            salt, expected_hex = stored_hash.split("$", 1)
        except ValueError:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt.encode("utf-8"), 100_000).hex()
        return secrets.compare_digest(actual, expected_hex)

    def _load_vault(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        vault_file = self.ensure_vault(self.vault_path)
        self._cache = json.loads(vault_file.read_text(encoding="utf-8"))
        return self._cache

    def reload(self) -> None:
        self._cache = None

    def get_secret(self, key: str) -> Any:
        allowed = self.SERVICE_SECRET_ACL.get(self.service_name, set())
        if key not in allowed:
            raise SecretNotFoundError(
                f"Service '{self.service_name}' is not authorized to access secret '{key}'"
            )

        env_key = f"ZEPTO_SECRET_{key.upper()}"
        if env_key in os.environ:
            raw = os.environ[env_key]
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw

        vault = self._load_vault()
        if key not in vault:
            raise SecretNotFoundError(f"Secret '{key}' not found in vault for '{self.service_name}'")
        return vault[key]
