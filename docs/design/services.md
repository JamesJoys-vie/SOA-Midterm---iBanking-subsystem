# Services: responsibilities, data and calls

Who owns which data, who calls whom, and what lives in Redis. Written from the code on `main` (2026-10-31).
Public request / response details: [`docs/api/endpoints.md`](../api/endpoints.md). Picture:
[`docs/diagrams/architecture.mmd`](../diagrams/architecture.mmd).

Rules every service follows: one MySQL database (and MySQL user) per service, no service reads another one's tables
or Redis keys; services talk only through REST calls and Redis Streams events; services are stateless (any state is
in MySQL or Redis), so they can run as several replicas.

## 1. Services

| Service | Owns (data) | Does | Called by |
|---|---|---|---|
| **gateway** | rate-limit counters (Redis) | single entry for `/api/*`: checks the JWT, drops any client `X-User-Id` and sets its own, rate limits, routes by an allow-list | web (nginx) |
| **user-service** | `users_db`: `users`, `accounts` (balance, `CHECK balance >= 0`, `version`), `ledger_entries` (one DEBIT / CREDIT per transaction), `transactions` (a copy of each final payment, served by `GET /history`) | login + JWT, profile, balance, conditional debit and refund, history | gateway, payment-service |
| **tuition-service** | `tuition_db`: `students`, `tuitions` (status `UNPAID` / `RESERVED` / `PAID`, hold owner + `reserved_until`) | tuition lookup by MSSV, reservation hold (one payment at a time per tuition), commit to `PAID`, release | gateway, payment-service |
| **payment-service** | `payments_db`: `transactions` (the saga state, `Idempotency-Key`), `outbox_events` | the payment workflow (orchestration saga) + background jobs: outbox relay, expiry / reconcile | gateway |
| **otp-service** | OTP keys (Redis, see section 4) | issue a 6-digit code, verify it once; publishes `otp.requested` | payment-service |
| **notification-service** | dedupe markers (Redis) | consumes `otp.requested` and `payment.completed`, sends the emails | - (events only) |
| **web** | - | nginx serving the React app, proxies `/api/` to the gateway | browser |

Ownership in short: **money and history are in user-service, the payment's progress is in payment-service**.
payment-service never touches a balance directly; it asks user-service to debit, and refunds by asking it to credit.

## 2. Calls (synchronous, REST)

Public routes, through the gateway (`/api` prefix removed before forwarding):

| Route | Goes to |
|---|---|
| `POST /auth/login`, `GET /users/me`, `GET /accounts/me`, `GET /history` | user-service |
| `GET /tuitions/{mssv}`, `GET /tuitions` | tuition-service |
| `POST /transactions`, `GET /transactions`, `GET /transactions/{id}`, `POST /transactions/{id}/verify-otp`, `/resend-otp`, `/cancel` | payment-service |

The web app reads history from `GET /transactions` (payment-service, includes pending and failed attempts);
`GET /history` and `GET /tuitions` are routed but not used by it.

Internal calls (compose network only, no JWT), all made by payment-service:

| To | Call | Used for |
|---|---|---|
| user | `GET /internal/users/{user_id}` | payer name, email and current balance (never taken from the client) |
| user | `POST /internal/accounts/debit` `{user_id, amount, transaction_id}` | take the money: only if `balance >= amount`, at most once per transaction (ledger unique key) -> `balance_after` |
| user | `POST /internal/accounts/credit` `{user_id, amount, transaction_id}` | refund (compensation of the debit), at most once per transaction |
| user | `POST /internal/history` `{user_id, student_id, tuition_id, amount, status, failure_reason}` | write the final result to the user's history (not idempotent, so never retried) |
| tuition | `GET /tuitions/{mssv}` | read the amount and status on the server |
| tuition | `POST /internal/tuitions/{id}/reserve` / `commit` / `release` `{transaction_id}` | hold the tuition for this payment, mark it `PAID`, or free it |
| otp | `POST /internal/otp` `{transaction_id, email, full_name}` | new code (replaces the previous one); 429 on cooldown / too many codes |
| otp | `POST /internal/otp/verify` `{transaction_id, otp}` | `{valid}` or `{valid: false, reason, attempts_left}` |

Every service also answers `GET /health`.

## 3. The payment workflow (payment-service saga)

| Step | Calls, in order | If a step fails |
|---|---|---|
| **initiate** (`POST /transactions`) | payer (user) -> tuition lookup -> create `PENDING_OTP` -> reserve (tuition) -> issue OTP (otp) | release the hold, transaction `FAILED` |
| **confirm** (`verify-otp`) | verify (otp) -> `PENDING_OTP` -> `PROCESSING` (conditional UPDATE, so only one confirm wins) -> complete | wrong code: stays `PENDING_OTP`, attempts left in the message |
| **complete** | re-check -> debit (user) -> commit (tuition) -> `SUCCESS` + outbox row `payment.completed` in the same DB transaction -> history (user) | refund (credit) if debited, release the hold, `FAILED` |
| **resend-otp** / **cancel** | new OTP (otp) / `PENDING_OTP` -> `CANCELLED`, then release (tuition) | - |

Background jobs in payment-service:
- **outbox relay** (every 1 s): publishes unpublished `outbox_events` rows to Redis Streams, then marks them published.
- **expiry / reconcile job** (every 5 s): `PENDING_OTP` past its OTP window -> `EXPIRED` + release; `PROCESSING` for
  more than 30 s -> run complete again (debit and commit are idempotent); `FAILED` that still needs a refund -> retry it.

## 4. Redis data

One Redis 7 (AOF on) is shared, but each service only uses its own key prefixes.

| Keys | Owner | Content | Expires |
|---|---|---|---|
| `otp:txn:<transaction_id>` | otp | hash `{code_hash, attempts}`: the one active OTP of a payment (SHA-256 of the code, never the code) | OTP lifetime (300 s) |
| `otp:code:<code_hash>` | otp | transaction id; makes an active code unique across payments | 300 s |
| `otp:issued:<transaction_id>` | otp | count of codes issued (max 4) | window of 4 x 300 s |
| `otp:cooldown:<transaction_id>` | otp | present = resend not allowed yet | 30 s |
| `otp:test:<transaction_id>` | otp | plain code, **only** when `OTP_TEST_ECHO=true` (load tests / race demo) | 300 s |
| `rl:<route>:<who>:<window>` | gateway | request counter (fixed window) | the window |
| `notif:sending:<type>:<id>` | notification | "a consumer is sending this email now" | 30 s |
| `notif:sent:<type>:<id>` | notification | "this email was sent" (skip redeliveries) | 24 h |
| `events:otp.requested`, `events:payment.completed` | producers below | event streams, consumer group `notification` | trimmed to ~10,000 entries |
| `events:dead:<type>` | notification (via `shared/events.py`) | events that failed 5 times or can never succeed, with `error`, `source_id`, `group` | trimmed to ~10,000 entries |

## 5. Events (asynchronous, Redis Streams)

| Event | Producer | Payload | Consumer |
|---|---|---|---|
| `otp.requested` | otp-service, on every issued code | `{email, full_name, otp_enc, transaction_id, expires_in}`; `otp_enc` = the code encrypted with `OTP_EVENT_KEY` (otp + notification only) | notification-service: OTP email |
| `payment.completed` | payment-service outbox relay, once per `SUCCESS` | `{email, full_name, transaction_id, student_id, amount, balance_after}` | notification-service: receipt email |

At-least-once: the consumer acks only after the email is sent, unacked events are taken over after 15 s, and the
`notif:sent:*` markers stop duplicates. Details in `backend/shared/events.py`.

## 6. Differences from the reference plan
The first diagrams were copied from the reference plan, which kept accounts and the ledger in payment-service. The
code puts **accounts, ledger and history in user-service** (`users_db`); payment-service keeps only the saga state
and the outbox, and debits / refunds through `POST /internal/accounts/debit` / `credit`. `erd.mmd`,
`architecture.mmd` and `docs/api/endpoints.md` were corrected to match (2026-10-31).

Known issue (user-service, not changed here): `POST /internal/history` for a user with no account stores
`account_id = "unknown-account"`, which breaks the `accounts` foreign key, so the call most likely fails with a 500.
payment-service only calls it for payers whose account it has just debited, so it does not happen in the normal flow.
