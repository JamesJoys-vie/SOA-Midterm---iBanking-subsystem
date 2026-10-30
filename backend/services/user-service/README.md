# user-service

User and authentication microservice for the Tuition Payment (iBanking) Subsystem.
Assigned developer: **Nguyen Duc Hieu (524H0087)**.

---

## 1. Role in the Architecture

```
Browser / Web SPA ──HTTP Bearer / POST /login──> API Gateway ──X-User-Id / Proxy──> user-service
                                                                                          │
                                                                                          └──> users database (own)
```

- **Database-per-Service**: `user-service` owns its isolated database containing `users`, `accounts`, `ledger_entries`, and `transactions`. No other service accesses this database directly.
- **Security & Authentication**:
  - Passwords hashed with `bcrypt` (salted).
  - Evaluates a **Dummy Hash** if the username is not found to prevent Timing Attacks.
  - Generates and verifies **JWT Access Tokens (HS256)** with a 30-minute TTL.
- **Data Consistency (Tasks 1 & 4)**:
  - Atomic conditional balance deduction: `UPDATE accounts SET balance = balance - :amount WHERE user_id = :id AND balance >= :amount`.
  - **Idempotency**: Checked against `ledger_entries` so that each `transaction_id` is debited at most once.
  - **Saga Compensation**: Supports `POST /internal/accounts/credit` to refund money if a later payment saga step fails.

---

## 2. Fulfillment of Project Requirements

| Section | Business Requirement | Implementation in user-service |
|---|---|---|
| **Task 1** | Login with username and password (no registration) | `POST /login` and `POST /auth/login`, bcrypt hash verification, JWT Bearer token |
| **Task 1** | Store full name, phone number, email, balance | `users` and `accounts` tables, exposed via `GET /me` (and `GET /users/me`, `GET /accounts/me`) |
| **Task 1** | Transaction history | `GET /history` and `GET /transactions` (sorted newest first) |
| **Task 1** | Only authenticated users access payment | `get_current_user_id` FastAPI dependency verifies JWT expiration and signature |
| **Task 2** | Payer info (name, phone, email) auto-filled, read-only | Provided by `GET /me` |
| **Task 2** | Payer available balance | Provided in `GET /me` and `GET /accounts/me` |
| **Task 4** | Re-check transaction and balance | Conditional update `WHERE balance >= :amount` |
| **Task 4** | Deduct money from payer account, at most once per txn_id | `POST /internal/accounts/debit` with idempotency ledger |
| **Task 4** | Refund on compensation (if commit fails) | `POST /internal/accounts/credit` |

---

## 3. Endpoints (API Specification)

### 3.1. Public Endpoints (Client via API Gateway)

1. `POST /auth/login` (or `POST /login`)
   - **Request**: `{"username": "alice", "password": "Password123!"}`
   - **Response (200)**:
     ```json
     {
       "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
       "token_type": "bearer",
       "expires_in": 1800
     }
     ```
   - **Error (401)**: `{"detail": "Invalid username or password"}`

2. `GET /me` (or `GET /users/me`)
   - **Headers**: `Authorization: Bearer <token>` or `X-User-Id: <uuid>` (forwarded by Gateway)
   - **Response (200)**:
     ```json
     {
       "id": "11111111-1111-5111-8111-111111111111",
       "username": "alice",
       "full_name": "Nguyen Van A",
       "phone": "0900000001",
       "email": "alice@example.com",
       "balance": "30000000.00"
     }
     ```

3. `GET /accounts/me`
   - **Response (200)**: `{"balance": "30000000.00"}`

4. `GET /history` (or `GET /transactions`)
   - **Response (200)**: Array of transaction history items (newest first).

### 3.2. Internal Endpoints (Service-to-Service)

1. `GET /internal/users/{user_id}`
   - Provides payer contact details (full name, email) for `payment-service` and `otp-service`.

2. `POST /internal/accounts/debit`
   - **Request**: `{"user_id": "...", "amount": "15000000.00", "transaction_id": "txn-uuid"}`
   - **Response (200)**:
     ```json
     {
       "success": true,
       "transaction_id": "txn-uuid",
       "balance_after": "15000000.00",
       "message": "Account debited successfully"
     }
     ```
   - **Error (422)**: `{"detail": "Insufficient balance to complete the tuition payment"}`

3. `POST /internal/accounts/credit`
   - **Request**: `{"user_id": "...", "amount": "15000000.00", "transaction_id": "txn-uuid"}`
   - **Response (200)**:
     ```json
     {
       "success": true,
       "transaction_id": "txn-uuid",
       "balance_after": "30000000.00",
       "message": "Account refunded successfully"
     }
     ```

---

## 4. Testing & Running

### Run unit and integration tests:
```bash
pytest backend/services/user-service/tests -v
```

### Run standalone dev server:
```bash
uvicorn app.main:app --port 8000 --reload
```
Interactive Swagger API documentation: http://localhost:8000/docs
