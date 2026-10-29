# otp-service

Issues and verifies the one-time codes that confirm a tuition payment.
Internal service: only payment-service calls it, it is not routed through the gateway.

## Place in the architecture

```
browser → gateway → payment-service ──HTTP──> otp-service ──HTTP──> notification-service ──SMTP──> Mailpit
                                                    └──> otp database (own)
```

- **Own database.** Only otp-service reads or writes `otps`; no other service touches it,
  and otp-service never reads another service's tables.
- **No knowledge of other domains.** `txn_id` is an opaque id owned by payment-service
  (no foreign key across services). Anything else it needs (payer email and name, MSSV,
  student name, amount for the email) is passed in by payment-service.
- **No mail server access.** The code is emailed through notification-service, which owns
  all email; otp-service only knows its URL and token.
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
| Sent by email | after the OTP is stored it is emailed via notification-service; if that fails the OTP is deleted and the call returns `503` |
| Resend wait | a new code for the same transaction needs `OTP_RESEND_COOLDOWN_SECONDS` (60) since the last one, else `429` with `retry_after` |
| Resend limit | at most `OTP_MAX_SENDS` (5) codes per transaction, else `429` |

Codes are stored as an HMAC (`OTP_SECRET`), never in plain text.
Statuses: `ACTIVE`, `USED`, `REVOKED`, `EXPIRED`, `LOCKED`.

## API

All `/otps*` calls need `X-Internal-Token: <INTERNAL_API_TOKEN>`, otherwise `401`.

`POST /otps` (first code and every resend)
`{"txn_id", "email", "payer_name", "mssv", "student_name", "amount"}`
→ `201 {"txn_id", "expires_at", "otp_expires_in", "sent_to": "a****@example.com", "resend_available_in", "sends_left"}`

The code is never in the response; it only goes out by email.

`POST /otps/verify` `{"txn_id": "...", "code": "123456"}` → `200 {"txn_id", "verified": true, "used_at"}`

Errors: `{"error": CODE, "message": "...", "attempts_left"?: n, "retry_after"?: seconds}`

| `error` | HTTP |
|---|---|
| `OTP_INVALID` (with `attempts_left`) | 400 |
| `OTP_EXPIRED` | 400 |
| `OTP_ALREADY_USED` | 400 |
| `OTP_LOCKED` | 400 |
| `OTP_NOT_FOUND` | 404 |
| `OTP_RESEND_TOO_SOON` (with `retry_after` and a `Retry-After` header) | 429 |
| `OTP_RESEND_LIMIT` | 429 |
| `EMAIL_UNAVAILABLE` | 503 |

`GET /health` → `{"status": "ok"}` · `GET /ready` → `200 {"status": "ready"}` or `503` when the database is down

## Config

See `.env.example`. `NOTIFICATION_TOKEN` must equal notification-service's `INTERNAL_API_TOKEN`.

## Run

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m uvicorn app.main:app --port 8000 --reload
```

Run notification-service on port 8001 (see its README) to receive real emails in Mailpit.
Tests use a fake notifier and a temporary SQLite file; the service itself expects PostgreSQL
(`DATABASE_URL`). Set `TEST_DATABASE_URL` to run the tests on PostgreSQL.