# otp-service

Issues and verifies the one-time codes that confirm a tuition payment.
Internal service: only payment-service calls it, it is not routed through the gateway.

## Place in the architecture

```
browser → gateway → payment-service ──HTTP──> otp-service ──> otp database (own)
```

- **Own database.** Only otp-service reads or writes `otps`; no other service touches it,
  and otp-service never reads another service's tables.
- **No knowledge of other domains.** `txn_id` is an opaque id owned by payment-service
  (no foreign key across services). Anything else it needs (e.g. the payer's email for
  segment 2) is passed in by the caller.
- **Stateless.** All state is in the database and every rule is enforced there, so any
  number of copies can run side by side.
- **Service-to-service auth.** `/otps*` require the `X-Internal-Token` header
  (`INTERNAL_API_TOKEN`), which only payment-service is given.
- **Deployable on its own.** Own `requirements.txt`, `Dockerfile` and env config; waits for
  its database on startup; `/health` (liveness) and `/ready` (database reachable) for
  Docker Compose health checks.

## Rules

| Requirement | How |
|---|---|
| Bound to one transaction | `otps.txn_id`; verify only matches the OTP of the given `txn_id` |
| No clash with another transaction's live OTP | partial unique index on `code_hash WHERE status = 'ACTIVE'`; a clash is retried with a new code |
| One live OTP per transaction | partial unique index on `txn_id WHERE status = 'ACTIVE'`; issuing again revokes the old one |
| Valid for at most 5 minutes | `expires_at = created_at + OTP_TTL_SECONDS` (300) |
| Used successfully only once | one conditional `UPDATE ... SET status='USED', used_at=now WHERE status='ACTIVE' AND ...` |
| Limited attempts | `attempts` counted atomically; at `OTP_MAX_ATTEMPTS` (3) the OTP becomes `LOCKED` |

Codes are stored as an HMAC (`OTP_SECRET`), never in plain text.
Statuses: `ACTIVE`, `USED`, `REVOKED`, `EXPIRED`, `LOCKED`.

## API

All `/otps*` calls need `X-Internal-Token: <INTERNAL_API_TOKEN>`, otherwise `401`.

`POST /otps` `{"txn_id": "..."}` → `201 {"txn_id", "expires_at", "otp_expires_in", "code": null}`

`POST /otps/verify` `{"txn_id": "...", "code": "123456"}` → `200 {"txn_id", "verified": true, "used_at"}`

Errors: `{"error": CODE, "message": "...", "attempts_left"?: n}`

| `error` | HTTP |
|---|---|
| `OTP_INVALID` (with `attempts_left`) | 400 |
| `OTP_EXPIRED` | 400 |
| `OTP_ALREADY_USED` | 400 |
| `OTP_LOCKED` | 400 |
| `OTP_NOT_FOUND` | 404 |

`GET /health` → `{"status": "ok"}` · `GET /ready` → `200 {"status": "ready"}` or `503` when the database is down

## Config

See `.env.example`. `OTP_DEBUG_RETURN_CODE=true` puts the plain code in the `POST /otps`
response; for local testing only, until email delivery is added.

## Run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Tests use a temporary SQLite file; the service itself expects PostgreSQL (`DATABASE_URL`).