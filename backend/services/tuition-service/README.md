# tuition-service

Tuition lookup and payment reservation management service for the iBanking subsystem.  
Assigned Member: **Nguyen Duc Hieu (524H0087)**.

---

## 1. System Architecture Role

```
Browser ──> API Gateway ──> tuition-service ──> tuition database (isolated)
                                    ^
                                    |
                          payment-service calls
                          /internal/* endpoints to
                          reserve / commit / release
```

- **Independent Database**: `tuition-service` exclusively owns 2 tables: `students` and `tuitions`. No other service accesses this database directly.
- **Atomic Conditional Updates**: All status transitions (`UNPAID -> RESERVED`, `RESERVED -> PAID`, `RESERVED -> UNPAID`) are executed via single atomic `UPDATE ... WHERE status = :expected` queries. The database engine (MySQL InnoDB) handles row-level locking natively. This guarantees that when two payers attempt to pay for the same student simultaneously, exactly one succeeds while the other receives an HTTP 409 Conflict.
- **Idempotency**: The same `transaction_id` can call `reserve` multiple times (extending the reservation TTL) and `commit` multiple times (returning `PAID`) safely without causing duplicate billing or race condition errors.

---

## 2. Work Breakdown & Task Mapping

| Item | Requirement | Implementation in tuition-service |
|---|---|---|
| **Task 2** | Enter Student ID (MSSV) → automatically query full student name and tuition amount | `GET /tuitions/{student_id}` and `GET /tuitions?mssv=` |
| **Task 2** | Full payment only; no partial payments allowed | Endpoints return fixed `amount` for the term; arbitrary payment inputs are rejected |
| **Task 2** | Prioritize the oldest unpaid term first | Sorted by `term ASC` |
| **Task 2** | Lock tuition (conditional reserve endpoint) | `POST /internal/tuitions/{id}/reserve` using `UPDATE WHERE status = 'UNPAID'` |
| **Task 4** | Mark-paid (only the transaction holding the lock) | `POST /internal/tuitions/{id}/commit` using `UPDATE WHERE status = 'RESERVED' AND reserved_by_txn = :txn_id` |
| **Task 4** | Release lock upon transaction failure/cancellation | `POST /internal/tuitions/{id}/release` using `UPDATE WHERE status = 'RESERVED' AND reserved_by_txn = :txn_id` |

---

## 3. Tuition State Machine

```
UNPAID ──[reserve txn-A]──> RESERVED (held by txn-A)
                                 │
                    ┌────────────┴─────────────┐
                    │                          │
              [commit txn-A]            [release txn-A]
                    │                  (cancel / expired)
                    ▼                          │
                  PAID                      UNPAID <──┘
```

---

## 4. API Specification

### 4.1. Public Endpoints (Clients call via API Gateway)

1. `GET /tuitions/{student_id}` or `GET /tuitions?mssv={mssv}`
   - Look up unpaid tuition for a student by Student ID (MSSV). Returns the oldest unpaid term.
   - **Success (200 OK)**:
     ```json
     {
       "tuition_id": "tuition-uuid",
       "student_id": "52100001",
       "student_name": "Pham Minh D",
       "term": "2025-HK1",
       "amount": "15000000.00",
       "status": "UNPAID"
     }
     ```
   - **Error (404 Not Found)**:
     ```json
     {
       "detail": "No student found with MSSV '52100001'"
     }
     ```

### 4.2. Internal Endpoints (Called directly by payment-service saga coordinator)

2. `POST /internal/tuitions/{tuition_id}/reserve`
   - Atomically locks tuition for this transaction (`UNPAID -> RESERVED`).
   - If the same `transaction_id` calls `reserve` again, the reservation window is extended (idempotent).
   - **Request Body**: `{"transaction_id": "txn-uuid"}`
   - **Success (200 OK)**: `TuitionInfo` with `status: "RESERVED"`
   - **Error (409 Conflict)**: Returned if already paid or currently locked by another transaction.

3. `POST /internal/tuitions/{tuition_id}/commit`
   - Marks tuition as `PAID`. Only the transaction holding the reservation lock can commit.
   - Idempotent: repeated calls with the same `transaction_id` return 200 OK without errors.
   - **Request Body**: `{"transaction_id": "txn-uuid"}`
   - **Success (200 OK)**:
     ```json
     {
       "status": "PAID",
       "message": "Tuition payment committed successfully"
     }
     ```
   - **Error (409 Conflict)**: Returned if the tuition is not in `RESERVED` state or is reserved by a different transaction.

4. `POST /internal/tuitions/{tuition_id}/release`
   - Reverts tuition status from `RESERVED` back to `UNPAID` when transaction expires or cancels.
   - **Request Body**: `{"transaction_id": "txn-uuid"}`
   - **Success (200 OK)**:
     ```json
     {
       "released": true,
       "message": "Tuition reservation released"
     }
     ```

---

## 5. Testing & Running

### Run Unit Tests (23 comprehensive test cases):
```bash
python -m pytest backend/services/tuition-service/tests -v
```

### Run Service Locally:
```bash
cd backend/services/tuition-service
uvicorn app.main:app --port 8000 --reload
```

Swagger API Docs available at: `http://localhost:8000/docs`
