# REST API

Public API: through the gateway, prefix `/api` (e.g. `POST /api/auth/login`). Everything except login needs
`Authorization: Bearer <jwt>`. The gateway verifies the token and passes the user id to the service as `X-User-Id`
(any client-sent `X-User-Id` is dropped). JSON in and out; money is a decimal string/number in VND.
Machine-readable specs, exported from the code: `docs/api/openapi/<service>.json` (they show the paths without
`/api` and with the `X-User-Id` header the gateway adds). Live versions: `/docs` on each service, inside the compose network only.

## 1. Public endpoints

| Method & path | Request | Success | Errors |
|---|---|---|---|
| POST /auth/login | `{username, password}` | 200 `{access_token, token_type: "bearer", expires_in}` (seconds, 1800) | 401, 429 |
| GET /users/me | - | 200 `UserProfile` | 401 |
| GET /accounts/me | - | 200 `{balance}` | 401, 404 (no account) |
| GET /tuitions/{mssv} | - | 200 `TuitionInfo` | 401, 404 (student / tuition not found) |
| POST /transactions (header `Idempotency-Key`, 8-64 chars, e.g. a UUID) | `{student_id}` | 201 `Transaction` with `status` `PENDING_OTP` and `otp_expires_in` (same key again -> the same transaction, also 201) | 400, 401, 404, 409 (paid / reserved / key used by another user), 422 (insufficient balance), 429, 502 |
| POST /transactions/{id}/verify-otp | `{otp}` (exactly 6 characters) | 200 `{transaction: Transaction, balance_after}`; `transaction.status` = `SUCCESS`, `FAILED` (see `failure_reason`, e.g. insufficient balance) or `PROCESSING` (still finishing, poll GET) | 400 (wrong / expired / locked OTP, message says which), 401, 404, 409, 410 (transaction expired), 422 (OTP not 6 characters), 429, 502 |
| POST /transactions/{id}/resend-otp | - | 200 `{otp_expires_in}` (old OTP stops working, window restarts) | 401, 404, 409, 410, 429 (`Retry-After`), 502 |
| POST /transactions/{id}/cancel | - | 200 `Transaction` with `status` `CANCELLED` (cancelling again also 200) | 401, 404, 409 |
| GET /transactions | - | 200 `Transaction[]`, newest first (max 100) | 401 |
| GET /transactions/{id} | - | 200 `Transaction` | 401, 404 |

Other users' transactions answer 404 (never 403), so ids cannot be probed.
`POST /transactions` also accepts an optional `term` field; it is currently ignored (the oldest unpaid term is paid).

### Response objects

| Object | Fields |
|---|---|
| `UserProfile` | `id` (UUID), `username`, `full_name`, `phone`, `email` |
| `TuitionInfo` | `tuition_id` (UUID), `student_id` (MSSV), `student_name`, `term`, `amount`, `status` (`UNPAID` / `RESERVED` / `PAID`). The oldest unpaid term is returned; if every term is paid, the latest one (`PAID`). A hold past `reserved_until` is shown as `UNPAID`. |
| `Transaction` | `id` (UUID), `student_id`, `amount`, `status`, `failure_reason` (null unless FAILED / CANCELLED / EXPIRED), `created_at`, `completed_at` (null until final), `otp_expires_in` (seconds left, only while `PENDING_OTP`, else null) |
| verify-otp result | `transaction` (`Transaction`), `balance_after` (balance right after the debit for `PROCESSING` / `SUCCESS`, else the current balance) |
| Error | `{"detail": "<message>"}`; for schema validation errors (422) `detail` is a list of `{loc, msg, type}` |

Times are UTC ISO-8601 without a zone (e.g. `2026-10-16T08:30:00`).

### Transaction status
`PENDING_OTP` -> `PROCESSING` (money debited) -> `SUCCESS`; or `FAILED` (reserve / OTP send / balance failure, or the
tuition commit was refused and the amount refunded), `CANCELLED` (by the user), `EXPIRED` (OTP not confirmed in time).
`PENDING_OTP` lasts as long as the newest OTP (5 min, restarted by resend-otp).

### Status codes used

| Code | Meaning here |
|---|---|
| 200 / 201 | OK / transaction created (or replayed by the same Idempotency-Key) |
| 400 | Bad input (Idempotency-Key length, empty `student_id`) or OTP rejected (wrong, expired, locked) |
| 401 | Missing / invalid / expired JWT, wrong login, or a token for a user that no longer exists |
| 404 | Unknown route, student, tuition, account, or transaction (incl. other users' transactions) |
| 409 | State conflict: tuition already paid or being paid, transaction not in the needed status, Idempotency-Key reused by another user |
| 410 | Transaction expired |
| 422 | Insufficient balance at initiate, or the request fails schema validation (missing header / field, OTP not 6 characters) |
| 429 | Rate limit (gateway) or OTP resend limit (otp-service); `Retry-After` says when to retry |
| 502 | A service the request depends on did not answer; safe to retry (`POST /transactions` with the same Idempotency-Key) |
| 503 | `Service busy`: the service's DB connection pool stayed exhausted for 5 s (overload); `Retry-After: 1` |

### Limits
Times in this document are the defaults (`.env`: `JWT_EXPIRE_MINUTES=30`, `OTP_TTL_SECONDS=300`,
`RESERVATION_TTL_SECONDS=600`); load-test mode shortens the OTP window to 60 s and the hold to 120 s.
Rate limits (gateway, Redis fixed window, 429 + `Retry-After`): login 10/min per IP; create transaction 20/min,
verify-otp 10/min, resend-otp 5/min per user. otp-service adds: 30 s between OTPs of one transaction, max 4 OTPs
(initial + 3 resends) per transaction, OTP burned after 5 wrong codes.
`RATE_LIMIT_MULTIPLIER` (gateway env, default 1) scales the gateway limits; only the load-test override raises it.

## 2. Internal endpoints (service to service, not routed by the gateway)
Called by payment-service only (its saga and its expiry / reconcile job). No JWT: reachable only on the compose network.

| Service | Method & path | Request | Success | Errors |
|---|---|---|---|---|
| user | GET /internal/users/{user_id} | - | 200 `UserProfile` (payer email + name for the OTP / receipt emails) | 404 |
| tuition | GET /tuitions/{mssv} | - | 200 `TuitionInfo` (same route as the public one, called directly) | 404 |
| tuition | POST /internal/tuitions/{tuition_id}/reserve | `{transaction_id}` | 200 `TuitionInfo` with `status` `RESERVED`; hold for 10 min. Same transaction again -> 200 and the hold is extended | 404, 409 (paid, or held by another transaction) |
| tuition | POST /internal/tuitions/{tuition_id}/commit | `{transaction_id}` | 200 `{status: "PAID"}` (also when already paid by this transaction) | 404, 409 (not reserved by this transaction) |
| tuition | POST /internal/tuitions/{tuition_id}/release | `{transaction_id}` | 200 `{released: true}`, or `{released: false}` if the hold is gone or not ours (no-op) | 404 |
| otp | POST /internal/otp | `{transaction_id, email, full_name}` | 201 `{expires_in}` (300 s); a new 6-digit code replaces the previous one and is emailed via `otp.requested` | 429 (`Retry-After`: cooldown or max OTPs), 503 (could not pick a unique code) |
| otp | POST /internal/otp/verify | `{transaction_id, otp}` | 200 `{valid: true}`, or `{valid: false, reason: "invalid" \| "expired" \| "locked", attempts_left}` (single-use: a correct code works once) | - |

Every service also has `GET /health` -> 200 `{status: "ok", service}`.

Load tests only: otp `GET /internal/test/otp/{transaction_id}` (latest plain code) exists only when `OTP_TEST_ECHO=true`
(set by `docker-compose.loadtest.yml`); otherwise the route is not mounted.

## 3. Events (Redis Streams, async)

| Stream | Producer | Consumer | Payload |
|---|---|---|---|
| `events:otp.requested` | otp-service, on every issued OTP | notification-service (group `notification`) | `{email, full_name, otp, transaction_id, expires_in}` |
| `events:payment.completed` | payment-service outbox relay, once per SUCCESS | notification-service (group `notification`) | `{email, full_name, transaction_id, student_id, amount, balance_after}` |

Delivery is at-least-once (XACK after the email is sent, un-acked messages are re-claimed), so the consumer skips
duplicates (Redis key per event, 24 h).
