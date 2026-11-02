# iBanking with Mircroservices Architecture
## Member:
- 524H0086: Tran Hong Nhat Duy
- 524H0087: Nguyen Duc Hieu
- 524H0081: Phan Huy Binh

## Layout
Same organization as the reference plan (`Project`):
- `backend/gateway`           API gateway: JWT check, `X-User-Id`, rate limit (Redis), allow-list routing
- `backend/services/*`        user, tuition, payment, otp, notification (each: `app/`, `tests/`; payment also has Alembic `migrations/`)
- `backend/shared`            JWT/bcrypt, DB helpers, Redis client, Redis Streams event bus (`events.py`)
- `backend/infra`             container entrypoint, MySQL init script (one database + one user per service)
- `backend/scripts`           `seed.py` (demo users, accounts, tuitions), `race_demo.py` (concurrency demo)
- `frontend`                  React + JavaScript (Vite) client, served by nginx
- `docs`                      API reference (`api/endpoints.md` + `api/openapi/`), service responsibilities
                              (`design/services.md`), diagrams, wireframes
- `tests`                     load/concurrency suite - planned

## Infrastructure
MySQL 8 (one database per service) + Redis 7 only. Redis is both the OTP store (keys with TTL) and the
event bus (Redis Streams + consumer groups, AOF persistence). No separate message broker.
Who owns which data and who calls whom: [docs/design/services.md](docs/design/services.md).

## OTP and email
- payment-service asks otp-service for a code; otp-service keeps only a SHA-256 of it in Redis (5 min TTL, single use,
  burned after 5 wrong codes, 30 s between codes, max 4 per payment) and publishes `otp.requested`.
- The code inside that event is encrypted (`otp_enc`, key `OTP_EVENT_KEY`, given to otp-service and
  notification-service only), so the stream, Redis' AOF file and dead letters never hold the plain code.
- notification-service reads `otp.requested` and `payment.completed` (consumer group `notification`) and sends the
  OTP and receipt emails. Delivery is at-least-once with no duplicate email; a failed send is retried every 15 s;
  after 5 tries, or at once when retrying cannot help (bad payload, address refused), the event moves to
  `events:dead:<type>` with the error (`docker compose exec redis redis-cli XRANGE events:dead:otp.requested - +`).
  An OTP email whose code has already expired is dropped instead of sent.
- Without `SMTP_USER` the emails are printed to the notification-service log (development only).

## Frontend
React 18 + Vite + Tailwind, TanStack Query; screens follow `docs/wireframes/wireframes.html`.
- `/login`, `/home` (balance, payment stats, payments waiting for an OTP with Resume / Cancel, recent transactions),
  `/pay` (payer, MSSV lookup, confirm -> OTP modal -> result), `/history` (search by MSSV, status filter, pages).
- One `Idempotency-Key` per payment attempt, so a retried "Confirm" never creates a second transaction.
- Nothing sensitive in the address bar: the token stays in `sessionStorage`, Resume passes the transaction id in
  router state, filters are component state; the URL only ever shows `/login`, `/home`, `/pay`, `/history`.
- Amounts are hidden by default (eye toggle, remembered per browser).

## Progress
| Part | Owner | State |
|---|---|---|
| Planning docs (API reference, OpenAPI, diagrams, wireframes) | Duy | done |
| `otp_service` (Redis OTP store, cooldown, single use, encrypted `otp.requested` event) + tests | Duy | done |
| `notification_service` (Streams consumer, dedupe, dead letters, SMTP / log mailer) + tests | Duy | done |
| `frontend` foundation: tooling, API client, auth, layout, UI kit, Login page | Duy | done |
| `frontend` `/pay` details step (payer, tuition lookup, confirm) | Duy | done |
| `frontend` OTP modal + Result, Home, History pages | Duy | done |
| `user-service` (login/JWT, profile, account, debit/credit, history) + tests | Hieu | done |
| `tuition-service` (lookup, reserve/commit/release hold) + tests | Hieu | done |
| `seed.py` (demo data) | Hieu | done |
| `gateway` (JWT guard, rate limiter, reverse proxy) + tests | Binh | done |
| `payment_service` (saga, idempotency, outbox relay, expiry job, Alembic migration) + tests | Binh | done |
| `docker-compose.yml` (MySQL, Redis, Adminer, all services, gateway, web, ngrok profile) | Binh | done |
| `race_demo.py` + `docker-compose.demo.yml` (same account / same tuition races) | Binh | done |
| Load tests (Locust, pytest races, invariant checker) | - | planned |

## Run
1. `Copy-Item .env.example .env` and fill in the passwords, `JWT_SECRET`, `OTP_EVENT_KEY` (command in
   `.env.example`; otp-service and notification-service do not start without it) and SMTP values
   (leave `SMTP_USER` empty to print emails to the log).
2. Whole system: `docker compose up -d --build` -> web http://localhost:8080, Adminer http://localhost:8081.
3. Demo data (once): `docker compose --profile tools run --rm seed` -> users `alice` / `bob` / `carol`
   (password `Password123!`) and 25 unpaid tuitions. Safe to run again (existing rows are skipped); paid tuitions
   stay paid, so start from scratch with `docker compose down -v` (deletes all data), then steps 2-3.
4. Public link (ngrok): `docker compose --profile public up -d`.
5. Race demo: `docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile demo run --rm race-demo all`
   (the demo override enables the OTP test echo; never use it on a real deployment).
6. `docker compose down`

Frontend alone: `cd frontend; npm install; npm run dev` (serves :5173, proxies `/api` to the gateway on :8080).

Tests (from each service folder, with `pip install -r backend/requirements.txt pytest fakeredis email-validator`):
`python -m pytest -q tests`. The otp-service and notification-service tests need a real Redis (db 15, flushed);
run them inside the compose network with the command at the top of `test_otp_store.py` / `tests/conftest.py`.
