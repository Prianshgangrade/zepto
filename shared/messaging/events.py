"""Versioned DomainEvent envelope with cryptographic integrity support."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class DomainEvent:
    event_type: str
    producer: str
    payload: dict[str, Any]
    correlation_id: str = ""
    schema_version: str = "1.0"
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    signature: str = ""

    def canonical_body(self) -> str:
        return json.dumps(
            {
                "event_id": self.event_id,
                "event_type": self.event_type,
                "schema_version": self.schema_version,
                "producer": self.producer,
                "correlation_id": self.correlation_id,
                "occurred_at": self.occurred_at,
                "payload": self.payload,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    def sign(self, hmac_key: str) -> "DomainEvent":
        digest = hmac.new(
            hmac_key.encode("utf-8"),
            self.canonical_body().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return DomainEvent(
            event_type=self.event_type,
            producer=self.producer,
            payload=self.payload,
            correlation_id=self.correlation_id,
            schema_version=self.schema_version,
            event_id=self.event_id,
            occurred_at=self.occurred_at,
            signature=digest,
        )

    def verify_signature(self, hmac_key: str) -> bool:
        if not self.signature:
            return False
        expected = hmac.new(
            hmac_key.encode("utf-8"),
            self.canonical_body().encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(self.signature, expected)
