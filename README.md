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
- `docs`                      API reference (`api/endpoints.md` + `api/openapi/`), diagrams, wireframes
- `tests`                     load/concurrency suite - planned

## Infrastructure
MySQL 8 (one database per service) + Redis 7 only. Redis is both the OTP store (keys with TTL) and the
event bus (Redis Streams + consumer groups, AOF persistence). No separate message broker.

## Progress
| Part | Owner | State |
|---|---|---|
| Planning docs (API reference, OpenAPI, diagrams, wireframes) | Duy | done |
| `otp_service` (Redis OTP store, cooldown, single use, `otp.requested` event) | Duy | done |
| `notification_service` (Streams consumer, dedupe, SMTP / log mailer) | Duy | done |
| `frontend` foundation: tooling, API client, auth, layout, UI kit, Login page | Duy | done |
| `frontend` `/pay` details step (payer, tuition lookup, confirm) | Duy | on branch `feat/frontend-payment-details`, PR not merged yet |
| `frontend` OTP modal + Result, Home, History pages | Duy | planned (placeholders now) |
| `user-service` (login/JWT, profile, account, debit/credit, history) + tests | Hieu | done |
| `tuition-service` (lookup, reserve/commit/release hold) + tests | Hieu | done |
| `seed.py` (demo data) | Hieu | done |
| `gateway` (JWT guard, rate limiter, reverse proxy) + tests | Binh | done |
| `payment_service` (saga, idempotency, outbox relay, expiry job, Alembic migration) + tests | Binh | done |
| `docker-compose.yml` (MySQL, Redis, Adminer, all services, gateway, web, ngrok profile) | Binh | done |
| `race_demo.py` + `docker-compose.demo.yml` (same account / same tuition races) | Binh | done |
| Load tests (Locust, pytest races, invariant checker) | - | planned |

## Run
1. `Copy-Item .env.example .env` and fill in the passwords, `JWT_SECRET` and SMTP values
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
`python -m pytest -q tests`. The otp-service tests need a real Redis (see the header of `test_otp_store.py`).
