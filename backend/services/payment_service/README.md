# payment-service

Owner: **Phan Huy Binh (524H0081)**. Runs the tuition payment workflow (assignment sections 2 -> 4) as an
**orchestration saga**: it owns no money and no tuition data, it calls the services that do and undoes earlier
steps when a later one fails.

## Layout
| Path | Role |
|---|---|
| `app/api/routes.py` | Public endpoints (`/transactions...`), thin: read request -> call `PaymentSaga` -> shape response |
| `app/api/deps.py` | `current_user_id` (from `X-User-Id`, set by the gateway), saga wiring |
| `app/domain/payment_saga.py` | **`PaymentSaga`**: `initiate`, `confirm`, `complete`, `resend_otp`, `cancel`, `expire`, compensation `_fail` |
| `app/domain/models.py` | Tables `transactions`, `outbox_events`; `TxnStatus` |
| `app/repositories/transaction_repo.py` | All SQL; `transition()` = conditional UPDATE (compare-and-set) |
| `app/clients/*` | `UserClient`, `TuitionClient`, `OtpClient` on a common `ServiceClient` (retry only idempotent calls) |
| `app/workers/expiry_job.py` | Expires PENDING_OTP + releases tuition, finishes stuck PROCESSING, retries refunds |
| `app/workers/outbox_relay.py` | Publishes `payment.completed` to Redis Streams -> notification-service emails the receipt |
| `app/core/*` | Settings, DB session, error -> HTTP status mapping |
| `migrations/` | Alembic (run automatically by `backend/infra/entrypoint.sh`) |
| `tests/` | Saga + HTTP tests with fakes (incl. both race conditions of section 5) |

## Endpoints (through the gateway: `/api` prefix, JWT required)
| Method & path | Result | Errors |
|---|---|---|
| `POST /transactions` (header `Idempotency-Key`) `{student_id}` | 201 `Transaction` PENDING_OTP | 400, 404, 409, 422, 429, 502 |
| `POST /transactions/{id}/verify-otp` `{otp}` | 200 `{transaction, balance_after}` | 400, 404, 409, 410, 502 |
| `POST /transactions/{id}/resend-otp` | 200 `{otp_expires_in}` | 404, 409, 410, 429, 502 |
| `POST /transactions/{id}/cancel` | 200 `Transaction` CANCELLED | 404, 409 |
| `GET /transactions`, `GET /transactions/{id}` | 200 | 404 |

Status: `PENDING_OTP -> PROCESSING -> SUCCESS`, or `FAILED` / `CANCELLED` / `EXPIRED`.

## Calls to other services (internal network)
user-service: `GET /internal/users/{id}`, `POST /internal/accounts/debit`, `POST /internal/accounts/credit` (refund),
`POST /internal/history` - tuition-service: `GET /tuitions/{mssv}`, `POST /internal/tuitions/{id}/reserve|commit|release`
- otp-service: `POST /internal/otp`, `POST /internal/otp/verify`.

## Tests
```
cd backend/services/payment_service
pip install -r ../../requirements.txt pytest
python -m pytest -q tests
```
