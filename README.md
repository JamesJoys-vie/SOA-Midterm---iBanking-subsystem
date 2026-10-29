# iBanking with Mircroservices Architecture
## Member:
- 524H0086: Tran Hong Nhat Duy
- 524H0087: Nguyen Duc Hieu
- 524H0081: Phan Huy Binh

## Layout
Same organization as the reference plan (`Project`):
- `backend/gateway`           API gateway (JWT check, routing) - planned
- `backend/services/*`        user, tuition, payment, otp, notification (each: `app/{api,core,domain,repositories,schemas,workers}`, `migrations/`, `tests/`)
- `backend/shared`            JWT/bcrypt, DB helpers, Redis client, Redis Streams event bus (`events.py`)
- `backend/infra`             container entrypoint (MySQL init script - planned)
- `backend/scripts/seed.py`   demo data - planned
- `frontend`                  React + JavaScript (Vite) client, served by nginx - planned
- `docs`                      API reference (`api/endpoints.md` + `api/openapi/`), diagrams, wireframes, `SCAFFOLD_LOG.md`
- `tests`                     load/concurrency suite - planned

## Infrastructure
MySQL 8 (one database per service) + Redis 7 only. Redis is both the OTP store (keys with TTL) and the
event bus (Redis Streams + consumer groups, AOF persistence). No separate message broker.

## Run (current state: otp-service + notification-service)
1. `Copy-Item .env.example .env` and fill in the SMTP values (or leave `SMTP_USER` empty to print emails to the log).
2. `docker compose up -d --build`
3. `docker compose logs notification-service` shows emails when SMTP is not configured.
4. `docker compose down`

Progress and decisions: `docs/SCAFFOLD_LOG.md`.
