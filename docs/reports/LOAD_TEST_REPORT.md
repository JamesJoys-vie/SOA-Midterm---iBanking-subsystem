# Load and concurrency test report

Date: 2026-11-02. Tool: Locust 2.44.4, plus pytest race tests and a database invariant checker (`tests/load/`).
Raw results per run: `docs/reports/<run>/` (`report.png` = Locust charts, drawn by
`tests/load/plot_report.py`, `stats_*.csv`, `outcomes.json` = business
outcomes, `invariants.json` = database checks).

## 1. Verdict
- **Money is always correct.** In every run, including the one where tuition-service collapsed, no balance went
  below 0, every balance change is explained by a ledger entry, no tuition was paid twice, and the money taken from
  the accounts equals the tuition marked paid. The failures before the fixes were about availability, never money.
- **Concurrency rules hold**: one winner per contested tuition, no overdraft from parallel confirms on one account,
  one transaction per Idempotency-Key, one debit per double-submitted OTP, cancel vs verify has one winner
  (race tests: 100 / 100 with 20 rounds per scenario).
- **3 bugs found and fixed** (section 5). Before the fixes, 150 users froze tuition-service (26 % of requests failed,
  still down minutes after the load stopped). After: 0 failed requests at 50, 150 and 300 users.
- **Capacity on this machine**: ~110-115 requests/s (~25 completed payments/s). Beyond that latency grows, not errors
  (300 users: median 2.1 s, p99 3.8 s). Next limits: gateway, tuition-service and user-service, one process each.

## 2. Setup
- Docker Desktop on Windows 11, 12 CPUs. Stack + Locust on the same host, isolated compose project.
- `docker-compose.yml` as it is (payment-service 4 uvicorn processes, the others 1) + `docker-compose.loadtest.yml`,
  which only changes what a test client needs: OTP readable through `GET /internal/test/otp/{id}` (`OTP_TEST_ECHO`),
  gateway rate limits x1000 (all virtual users share one IP), OTP window 60 s / tuition hold 120 s (abandoned
  payments expire during a run), SMTP off (emails go to the notification-service log).
- Traffic goes through nginx -> gateway like the browser. Every run starts from `lt_data.py reset`: 347 users,
  653 students, 30,003 unpaid tuitions, apart from the demo data (`lt-` users, `LT` students).
- Levels: 3 minutes each; `run_level.sh <name> <users> <spawn rate> 3m`.

## 3. What the virtual users do
| User type (share) | Behaviour | Expected |
|---|---|---|
| Payer (80 %) | own account + own student: lookup -> initiate -> OTP -> verify; balance and history views | SUCCESS |
| | sometimes on a spare student: wrong OTP then right one, cancel, abandon, same OTP 3x at once, same Idempotency-Key 3x at once, resend right away | 400 then SUCCESS, CANCELLED, EXPIRED, one debit, one transaction, 429 then SUCCESS |
| Hot student (10 %) | 40 accounts fight for the same 10 students (100 terms each) | one reservation per term, the others 409 |
| Shared account (10 %) | several users on 5 accounts of 150M, often confirming two payments at the same moment | 422 at initiate or FAILED "Insufficient balance" at verify, never below 0 |

Checks after every run (`verify_invariants.py`, read from the three databases after the background jobs settle):
**I1** no negative balance; **I2** balance = seed - debits + refunds; **I3** ledger matches each transaction's status,
amount and account; **I4** SUCCESS <-> PAID tuition one to one; **I5** no tuition paid twice; **I6** money out = tuition
paid; **I7** one published `payment.completed` per SUCCESS; **I8** nothing stuck (PROCESSING, PENDING_OTP, refund
pending). Warnings: **W1** stale tuition holds, **W2** user-service history rows per status vs payment-service.

Differences from the reference plan's checker: accounts, ledger and history are in users_db (user-service), not in
payments_db, and a transaction is tied to its account through `payer_user_id`. A duplicate confirm can also get
`409 Transaction is PROCESSING` here (the first one is still finishing); the tests accept it next to 400.

## 4. Results
| Run | Users (spawn/s) | Requests | Failed | req/s | Median | p95 | p99 | SUCCESS | Invariants |
|---|---|---|---|---|---|---|---|---|---|
| medium-before-fix | 150 (10) | 3,435 | 891 (26 %) | 16.5 | 470 ms | 33 s | 34 s | 279 | **failed** (stuck PROCESSING) |
| small | 50 (5) | 18,065 | 0 | 101.0 | 37 ms | 210 ms | 310 ms | 3,775 | pass |
| medium | 150 (10) | 20,920 | 0 | 115.9 | 640 ms | 2.0 s | 2.4 s | 4,636 | pass |
| stress | 300 (20) | 20,166 | 0 | 109.4 | 2.1 s | 3.4 s | 3.8 s | 4,424 | pass |

Charts: `medium-before-fix/report.png` shows the collapse (requests/s falls from ~100 to ~15 after 28 s, p95 climbs
to 20-32 s); `medium/report.png` and `stress/report.png` stay flat with no failures.

`small` ran after fixes 2-3 but before fix 1 of section 5 (50 users were not enough to freeze tuition-service);
`medium` and `stress` ran with all three.
Business outcomes in the stress run (`stress/outcomes.json`): every flow gave its expected answer, e.g. 92
double-submits -> exactly one 200 each, 85 duplicate-key bursts -> 3x the same transaction each, 95 early resends -> 429,
777 shared-account initiates -> 422 and 7 parallel confirms -> FAILED "Insufficient balance".

## 5. Bugs found and fixed
1. **tuition-service froze at 150 users** (`medium-before-fix`). Its routes used the request-scoped `Depends(get_db)`:
   the session keeps its connection while FastAPI validates the response in a second threadpool step, so under load
   every connection waits for a thread and every thread for a connection. With the default pool (5 + 10, 30 s wait,
   longer than the gateway's 20 s) dead requests piled up; `/health` (sync, same threadpool) failed and Docker marked
   the service unhealthy. It stayed frozen after the load stopped. user-service has the same code.
   **Fix** (user-service and tuition-service, `app/db.py`, `app/main.py`): `Depends(get_db, scope="function")` on every
   route, pool 10 + 20 (`DB_POOL_SIZE` / `DB_MAX_OVERFLOW`) with a 5 s wait, pool timeout -> 503 + Retry-After,
   `async def health`. MySQL `--max-connections=300` in `docker-compose.yml` (the pools can now open ~180 > 151).
   The 28 payments left in PROCESSING were finished by payment-service's expiry job once tuition-service came back.
2. **Parallel duplicates of one Idempotency-Key could get 409** "This tuition is being paid by another transaction":
   the twin created its transaction and held the tuition after our key check. **Fix** (`payment_saga.initiate`):
   on that 409 look the key up again and return the twin's transaction (+ unit test).
3. **...but the second look saw nothing** (1 of 40 race rounds still failed): `find_by_key` left its read transaction
   open, so under REPEATABLE READ the re-check read the same snapshot, and the connection stayed checked out during
   the remote calls after it. **Fix** (`transaction_repo.find_by_key`): end the read right after the lookup.

## 6. Limits and what to do next (not changed)
- **CPU** (one-off `docker stats` sample, 30 readings during an extra 80 s run at 300 users): gateway avg 86 % / max 141 %, tuition-service
  89 % / 152 %, user-service 175 % avg (up to 1025 % while 300 bcrypt logins run), payment-service 121 % over 4
  processes, MySQL 58 %. The single-process Python services are at about one core: more uvicorn workers for gateway,
  tuition-service and user-service (`entrypoint.sh` already reads `UVICORN_WORKERS`) is the next step.
- **Login burst**: in that extra run the users were spawned at 50/s; 4 of 300 logins got `503 Service busy` (0.06 %
  of the requests) because each login keeps its DB connection while bcrypt runs. That is the new busy answer working
  (before the fix the service would hang); reading the user, ending the read, then checking the password would free
  the connection sooner.
- Not done: frontend end-to-end tests.

## 7. How to run
```
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest run --rm loadtest python lt_data.py seed
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest run --rm loadtest pytest -v
docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest run --rm loadtest sh run_level.sh medium 150 10 3m
```
`RACE_ROUNDS=20` (`-e`) repeats each race test more often. The Locust web UI: `... run --rm --service-ports loadtest
locust -f locustfile.py` -> http://localhost:8089. Do not use load-test mode for a demo.
