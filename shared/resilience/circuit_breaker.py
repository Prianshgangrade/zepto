"""Async 3-state Circuit Breaker (CLOSED -> OPEN -> HALF_OPEN) for fault isolation."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, TypeVar


T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenError(RuntimeError):
    """Raised immediately when calls are blocked because the circuit is OPEN."""

    def __init__(self, name: str, retry_after_seconds: float) -> None:
        self.name = name
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Circuit breaker '{name}' is OPEN (retry in {retry_after_seconds:.1f}s)")


@dataclass(frozen=True)
class CircuitSnapshot:
    name: str
    state: CircuitState
    failure_count: int
    opened_count: int
    last_error: str | None


class CircuitBreaker:
    """Thread/coroutine-safe circuit breaker guarding synchronous downstream calls."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 12.0,
        half_open_max_calls: int = 1,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.half_open_max_calls = half_open_max_calls
        self._clock = clock or time.monotonic

        self._lock = asyncio.Lock()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: float | None = None
        self._opened_count = 0
        self._half_open_inflight = 0
        self._last_error: str | None = None

    def snapshot(self) -> CircuitSnapshot:
        return CircuitSnapshot(
            name=self.name,
            state=self._evaluate_state(),
            failure_count=self._failure_count,
            opened_count=self._opened_count,
            last_error=self._last_error,
        )

    def _evaluate_state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            elapsed = self._clock() - self._opened_at
            if elapsed >= self.recovery_timeout_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    async def _before_call(self) -> CircuitState:
        async with self._lock:
            current = self._evaluate_state()
            if current == CircuitState.OPEN:
                assert self._opened_at is not None
                remaining = max(0.0, self.recovery_timeout_seconds - (self._clock() - self._opened_at))
                raise CircuitBreakerOpenError(self.name, remaining)

            if current == CircuitState.HALF_OPEN:
                if self._state != CircuitState.HALF_OPEN:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_inflight = 0
                if self._half_open_inflight >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(self.name, 1.0)
                self._half_open_inflight += 1
            return current

    async def _on_success(self, used_state: CircuitState) -> None:
        async with self._lock:
            if used_state == CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._last_error = None

    async def _on_failure(self, used_state: CircuitState, exc: Exception) -> None:
        async with self._lock:
            self._last_error = f"{type(exc).__name__}: {exc}"
            if used_state == CircuitState.HALF_OPEN:
                self._half_open_inflight = max(0, self._half_open_inflight - 1)
                self._trip_open()
                return

            self._failure_count += 1
            if self._failure_count >= self.failure_threshold:
                self._trip_open()

    def _trip_open(self) -> None:
        self._state = CircuitState.OPEN
        self._opened_at = self._clock()
        self._opened_count += 1

    async def call(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Executes `fn` guarded by the circuit breaker."""
        state_at_entry = await self._before_call()
        try:
            result = await fn()
        except Exception as exc:
            await self._on_failure(state_at_entry, exc)
            raise
        await self._on_success(state_at_entry)
        return result

    async def reset(self) -> None:
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._half_open_inflight = 0
            self._last_error = None
