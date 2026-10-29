# notification-service

Sends every iBanking email: the OTP code (section 3) and the success receipt (section 4).
Internal service: only otp-service and payment-service call it, it is not routed through the gateway.

## Place in the architecture

```
payment-service ──┬──> otp-service ──HTTP──┐
                  └────────HTTP────────────┴──> notification-service ──SMTP──> Mailpit
                                                        └──> notification database (own)
```

- **Only owner of email.** No other service talks to the mail server or holds templates.
- **Own database.** Only notification-service uses `sent_emails`; it never reads other services' tables.
- **Gets everything in the request.** Callers send the address, names and amounts; it looks nothing up.
  `txn_id` is an opaque id from payment-service (no foreign key).
- **Stateless.** The "send once" rule is enforced by a unique constraint, so several copies can run.
- **Service-to-service auth.** `/emails/*` require `X-Internal-Token` (`INTERNAL_API_TOKEN`).
- **Deployable on its own.** Own `requirements.txt`, `Dockerfile`, env config, `/health` and `/ready`.

## Emails

| Email | Sent by | Content | Repeats |
|---|---|---|---|
| OTP | otp-service | code, minutes valid, MSSV, student, amount, "never share" warning | every call sends (resends are new codes); the code is never stored |
| Receipt | payment-service | transaction id, MSSV, student, term, amount, new balance, time (UTC+7) | once per `txn_id`; a retry answers `already_sent` |

Each email has a plain-text and an HTML part (Jinja2 templates in `app/templates/`; HTML is auto-escaped).
The OTP code is kept out of the subject so it doesn't show in lock-screen previews.

## API

All `/emails/*` calls need `X-Internal-Token: <INTERNAL_API_TOKEN>`, otherwise `401`.

`POST /emails/otp`
`{"to", "payer_name", "code", "expires_in", "mssv", "student_name", "amount"}` → `200 {"status": "sent"}`

`POST /emails/receipt`
`{"txn_id", "to", "payer_name", "mssv", "student_name", "term", "amount", "balance_after", "completed_at"}`
→ `200 {"status": "sent" | "already_sent"}`

Mail server down: `503 {"error": "EMAIL_UNAVAILABLE", "message": "..."}`. Nothing is recorded, so the caller can retry.

`GET /health` → `{"status": "ok"}` · `GET /ready` → `200` or `503` when the database is down

## Config

See `.env.example`. The SMTP defaults fit Mailpit (`localhost:1025`, no login, no TLS).

## Run

```bash
docker run -d --name mailpit -p 1025:1025 -p 8025:8025 axllent/mailpit
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest
.venv/Scripts/python -m uvicorn app.main:app --port 8001 --reload
```

Open http://localhost:8025 to see the emails Mailpit caught.
Tests use a fake mailer and a temporary SQLite file; `tests/test_mailpit.py` also sends a real
email when Mailpit is running (skipped otherwise). Set `TEST_DATABASE_URL` to run the tests on PostgreSQL.
