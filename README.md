# iBanking – Tuition Payment Subsystem

![Python](https://img.shields.io/badge/Python-3.12%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.121%2B-009688?logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![MySQL](https://img.shields.io/badge/MySQL-8.4-4479A1?logo=mysql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker%20Compose-ready-2496ED?logo=docker&logoColor=white)

A service-oriented internet-banking subsystem that lets a payer settle a student's tuition from their bank
account, with each payment confirmed by a one-time password (OTP) sent by email. The system is built as five
FastAPI microservices behind an API gateway, with a React single-page client.

> Midterm project – Service-Oriented Architecture.

## Table of Contents
- [Key Features](#key-features)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Repository Structure](#repository-structure)
- [Getting Started](#getting-started)
- [Configuration](#configuration)
- [Testing](#testing)
- [Documentation](#documentation)
- [Team and Contributions](#team-and-contributions)

## Key Features
- **Secure payment flow** – tuition lookup by student ID (MSSV), balance reservation, OTP confirmation and
  receipt email, coordinated by a saga in the payment service.
- **Duplicate-safe payments** – an `Idempotency-Key` per payment attempt guarantees that a retried confirmation
  never creates a second transaction.
- **Hardened OTPs** – only a SHA-256 hash is stored, with a 5-minute TTL, single use, lockout after 5 wrong
  attempts, a 30-second resend cooldown and a cap of 4 codes per payment.
- **Reliable notifications** – event-driven email delivery over Redis Streams, at-least-once with
  de-duplication, automatic retries and a dead-letter stream.
- **Edge protection** – JWT validation, Redis-backed rate limiting and allow-list routing at the gateway.
- **Concurrency-safe** – verified against same-account and same-tuition race conditions with dedicated
  load and race tests.

## Architecture

```mermaid
flowchart LR
  Browser([Browser]) --> WEB[Web<br/>nginx + React]
  WEB -->|/api/*| GW[API Gateway]
  GW --> US[User Service]
  GW --> TS[Tuition Service]
  GW --> PS[Payment Service]
  PS --> US
  PS --> TS
  PS --> OTP[OTP Service]
  PS -. payment.completed .-> RS[(Redis Streams)]
  OTP -. otp.requested .-> RS
  RS -.-> NS[Notification Service]
  NS -->|SMTP| MAIL[(Mail server)]
```

Solid arrows are synchronous REST calls; dashed arrows are asynchronous events. The detailed diagram is in
[docs/diagrams/architecture.mmd](docs/diagrams/architecture.mmd).

| Component | Responsibility | Data store |
|---|---|---|
| **API Gateway** | Single entry point for `/api/*`: JWT check, `X-User-Id` propagation, rate limiting, allow-list routing | Redis (rate-limit counters) |
| **User Service** | Login and JWT issuance, profile, account balance, debit / credit, transaction history | MySQL `users_db` |
| **Tuition Service** | Tuition lookup, reserve / commit / release of tuition holds | MySQL `tuition_db` |
| **Payment Service** | Transaction lifecycle (saga), idempotency, transactional outbox relay, expiry and reconciliation job | MySQL `payments_db` |
| **OTP Service** | Issues and verifies OTPs; publishes `otp.requested` | Redis (OTP keys with TTL) |
| **Notification Service** | Consumes `otp.requested` and `payment.completed`; sends OTP and receipt emails | Redis Streams |

### Design Principles
- **Database per service** – each service owns its own MySQL database and user; services communicate only
  through REST APIs and events.
- **Lightweight infrastructure** – MySQL 8 and Redis 7 only. Redis acts as both the OTP store and the event
  bus (Streams with consumer groups, AOF persistence); no separate message broker is required.
- **Encrypted events** – the OTP inside `otp.requested` is encrypted (`otp_enc`, key `OTP_EVENT_KEY`). The key
  is generated on first start by `otp-key-init` and mounted only into the OTP and notification services, so
  the stream, the AOF file and dead letters never contain a plain code.
- **Resilient delivery** – failed emails are retried every 15 seconds. After 5 attempts, or immediately for
  non-retryable errors (invalid payload, rejected address), the event is moved to `events:dead:<type>` with
  the error. OTP emails whose code has already expired are discarded.
- **Privacy in the client** – the token is kept in `sessionStorage`, and transaction IDs and filters never
  appear in the URL. Amounts are hidden by default.

Service ownership and call relationships are documented in [docs/design/services.md](docs/design/services.md).

## Technology Stack
| Layer | Technologies |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy 2, Alembic, Pydantic, PyJWT, bcrypt, httpx |
| Frontend | React 18, Vite, Tailwind CSS, TanStack Query, served by nginx |
| Data | MySQL 8.4, Redis 7 (key-value store and Streams) |
| Infrastructure | Docker, Docker Compose, Adminer |
| Testing | pytest, fakeredis, Locust |

## Repository Structure
```text
.
├── backend/
│   ├── gateway/            # API gateway
│   ├── services/           # user, tuition, payment, otp, notification (each with app/ and tests/)
│   ├── shared/             # JWT/bcrypt, DB helpers, Redis client, Redis Streams event bus
│   ├── infra/              # container entrypoint, MySQL init script (one database + user per service)
│   └── scripts/            # seed.py (demo data), race_demo.py (concurrency demo)
├── frontend/               # React + Vite client
├── docs/                   # API reference, OpenAPI specs, design notes, diagrams, reports
├── tests/load/             # load and concurrency test suite
├── docker-compose.yml          # full stack
├── docker-compose.demo.yml     # race-condition demo overlay
└── docker-compose.loadtest.yml # load-test overlay
```

## Getting Started

### Prerequisites
| Tool | Version | Required for |
|---|---|---|
| Docker Desktop | latest | Running the full stack |
| Python | 3.12+ | Local virtual environment (unit tests, IDE support) |
| Node.js | 18+ | Running the frontend outside Docker (optional) |

### 1. Clone the repository
```bash
git clone https://github.com/JamesJoys-vie/SOA-Midterm---iBanking-subsystem.git
cd SOA-Midterm---iBanking-subsystem
```

### 2. Set up the Python virtual environment
The services run inside Docker, so this step is not required to start the application. It is needed to run
the unit tests locally and to enable IDE code completion. The `.venv/` folder is excluded from Git.

**Windows (PowerShell)**
```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend/requirements.txt pytest fakeredis
```

> If PowerShell blocks `Activate.ps1`, allow local scripts for the current user and activate again:
> ```powershell
> Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
> ```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r backend/requirements.txt pytest fakeredis
```

Run `deactivate` to leave the environment. In VS Code, select the `.venv` interpreter through
**Python: Select Interpreter**.

### 3. Configure the environment
```powershell
Copy-Item .env.example .env     # Windows
```
```bash
cp .env.example .env            # macOS / Linux
```
Review the values in `.env` before starting; see [Configuration](#configuration).

### 4. Start the stack
```bash
docker compose up -d --build
```
This builds all images, starts every service and seeds the demo data.

### 5. Access the application
| Service | URL |
|---|---|
| Web application | http://localhost:8080 |
| Adminer (database UI) | http://localhost:8081 |
| MySQL (host access) | `127.0.0.1:3307` |

**Demo account:** username `alice`, password `Password123!`. Use student ID `52100001` to make a test payment.

Until SMTP is configured, emails (including OTP codes) are written to the notification service log:
```bash
docker compose logs notification-service
```
To inspect undeliverable events:
```bash
docker compose exec redis redis-cli XRANGE events:dead:otp.requested - +
```

### 6. Stop the stack
```bash
docker compose down        # stop and keep data
docker compose down -v     # stop and delete all data
```

### Optional
**Race-condition demo** (same account / same tuition). It enables an OTP test echo and must never be used on a
real deployment.
```bash
docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile demo run --rm race-demo all
```

**Frontend development server** on http://localhost:5173 (proxies `/api` to the gateway on port 8080):
```bash
cd frontend
npm install
npm run dev
```

## Configuration
All settings are read from `.env` (template: `.env.example`).

| Variable | Purpose |
|---|---|
| `MYSQL_ROOT_PASSWORD`, `USER_DB_PASSWORD`, `TUITION_DB_PASSWORD`, `PAYMENT_DB_PASSWORD` | Database credentials (one user per service) |
| `MYSQL_HOST_PORT` | Host port for MySQL (default `3307`, bound to localhost) |
| `WEB_HOST_PORT` | Host port for the web application (default `8080`) |
| `JWT_SECRET`, `JWT_EXPIRE_MINUTES` | Token signing key and lifetime |
| `OTP_TTL_SECONDS`, `RESERVATION_TTL_SECONDS` | OTP and tuition-hold lifetimes |
| `PAYMENT_WORKERS` | Number of payment service processes (default `4`) |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Outgoing email (Mailtrap or Gmail App Password). Leave `SMTP_USER` empty to log emails instead |

## Testing

### Unit tests
With the virtual environment active, run the tests from a service folder, for example:
```bash
cd backend/services/payment_service
python -m pytest -q tests
```
The OTP and notification service tests require a real Redis instance (database 15, flushed on each run).
Run them inside the Compose network using the command documented at the top of
`otp_service/tests/test_otp_store.py` and `notification_service/tests/conftest.py`.

### Load and concurrency tests
The suite in `tests/load/` uses Locust, pytest race tests and an invariant checker. Results and analysis are
published in [docs/reports/LOAD_TEST_REPORT.md](docs/reports/LOAD_TEST_REPORT.md).

> **Warning:** load-test mode exposes OTPs and lifts rate limits. Do not use it for demonstrations.

1. Start the stack in load-test mode:
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.loadtest.yml up -d --build
   ```
2. Run the test container with the same two `-f` files plus `--profile loadtest run --rm loadtest`, followed
   by one of:

   | Command | Purpose |
   |---|---|
   | `python lt_data.py seed` | Seed load-test data (run once) |
   | `pytest -v` | Race-condition tests |
   | `sh run_level.sh medium 150 10 3m` | Run one load level (writes to `docs/reports/medium/`) |

## Documentation
| Document | Description |
|---|---|
| [docs/api/endpoints.md](docs/api/endpoints.md) | REST API reference: public and internal endpoints, events |
| [docs/api/openapi/](docs/api/openapi/) | OpenAPI specifications |
| [docs/design/services.md](docs/design/services.md) | Service responsibilities and data ownership |
| [docs/diagrams/](docs/diagrams/) | Architecture, class, ERD and use-case diagrams |
| [docs/reports/LOAD_TEST_REPORT.md](docs/reports/LOAD_TEST_REPORT.md) | Load and concurrency test results |

## Team and Contributions
| Student ID | Name | Contributions |
|---|---|---|
| 524H0086 | Tran Hong Nhat Duy | Planning documents (API reference, OpenAPI, diagrams, wireframes); OTP service; notification service; frontend (foundation, payment flow, OTP modal, Home and History pages); load and concurrency tests |
| 524H0087 | Nguyen Duc Hieu | User service; tuition service; demo data seeding (`seed.py`) |
| 524H0081 | Phan Huy Binh | API gateway; payment service (saga, idempotency, outbox relay, expiry job, Alembic migration); Docker Compose setup; race-condition demo |

All components listed above are complete and covered by tests.
