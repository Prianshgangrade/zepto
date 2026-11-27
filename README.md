# Zepto-Like Microservices Application

Quick-commerce microservices application built strictly around the specified architecture and bounded contexts:

- **Front End** (`frontend/`) — React + Vite storefront (`Catalogues`, `Cart`, `Orders`, `Payments` checkout, `Notification` inbox)
- **API Gateway** (`services/api_gateway/`) — Port `8000`
- **Catalogues** (`services/catalogues/`) — Port `8001`, DB `data/catalogues.db`
- **Cart** (`services/cart/`) — Port `8002`, DB `data/cart.db`
- **Orders** (`services/orders/`) — Port `8003`, DB `data/orders.db`
- **Payments** (`services/payments/`) — Port `8004`, DB `data/payments.db`
- **Notification** (`services/notification/`) — Port `8005`, DB `data/notification.db`

## Architecture Mapping

1. **DDD, Single Responsibility Principle, Stateless Services**: Each service has `domain/`, `application/`, `infrastructure/`, and `api/` layers with zero in-memory session state.
2. **Database-per-Service**: Isolated SQLite WAL database per service (`data/<service>.db`).
3. **Eventual Consistency, Communication & Integration**:
   - **API Gateway**: Single entry point with versioned routing (`/api/v1/...`, `/api/v2/catalogues/...` + `X-API-Version` / `Deprecation` headers).
   - **Sync vs. Async**: Sync HTTP (`Gateway -> Services`, `Cart -> Catalogues`, `Orders -> Catalogues / Payments`) and Async Event Bus + Transactional Outbox (`OrderCreated` -> clears Cart & notifies; `PaymentSucceeded` / `PaymentFailed` -> converges Order status, compensates stock on failure, notifies; `OrderCancelled` -> releases stock, refunds payment, notifies).
4. **Resilience & Fault Tolerance**: Per-dependency 3-state `CircuitBreaker` (`CLOSED`, `OPEN`, `HALF_OPEN`), strict HTTP timeouts, and Graceful Degradation (Gateway cached catalogues & empty notification fallback, Cart cached snapshot fallback, Orders `PAYMENT_PENDING` fallback on payment outage).
5. **Security**: Zero-Trust dual-token auth (`Authorization: Bearer <user_jwt>` + short-lived `X-Service-Token` with service allowlists), HMAC-signed async events, and scoped `SecretsManager` with `kid` key rotation (`scripts/bootstrap_secrets.py`).

## Quick Start

```bash
python scripts/bootstrap_secrets.py
python run_all.py --with-frontend
```

Run tests:

```bash
pytest
```
