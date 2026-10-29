# user-service

Dịch vụ người dùng & xác thực cho phân hệ Thanh toán học phí (iBanking).
Thành viên phụ trách: **Nguyễn Đức Hiệu (524H0087)**.

---

## 1. Vị trí trong kiến trúc hệ thống

```
Trình duyệt / Web SPA ──HTTP Bearer / POST /login──> API Gateway ──X-User-Id / Proxy──> user-service
                                                                                             │
                                                                                             └──> users database (riêng)
```

- **Cơ sở dữ liệu độc lập (Database-per-Service)**: `user-service` sở hữu cơ sở dữ liệu riêng chứa các bảng `users`, `accounts`, `transactions`, `debit_ledger`. Không có dịch vụ nào khác được truy cập trực tiếp vào DB này.
- **Xác thực bảo mật**:
  - Mật khẩu lưu dưới dạng hash bằng thuật toán `bcrypt` có salt ngẫu nhiên.
  - Sử dụng kỹ thuật **Dummy Hash** để phòng chống tấn công dò username qua chênh lệch thời gian phản hồi (Timing Attack).
  - Cấp phát và xác thực mã **JWT Access Token (HS256)** có thời hạn 30 phút theo chuẩn phân hệ iBanking.
- **Tính nhất quán dữ liệu**:
  - Trừ tiền có điều kiện nguyên tử: `UPDATE accounts SET balance = balance - :amount WHERE user_id = :id AND balance >= :amount`.
  - Đảm bảo **Idempotency**: kiểm tra bảng `debit_ledger` để cam kết mỗi mã giao dịch `transaction_id` chỉ trừ tiền đúng 1 lần duy nhất.

---

## 2. Đáp ứng các yêu cầu trong bảng "Phân công công việc"

| Mục | Yêu cầu nghiệp vụ | Triển khai trong user-service |
|---|---|---|
| **Mục 1** | Đăng nhập bằng username và password (không có đăng ký) | `POST /login` và `POST /auth/login`, mã hóa bcrypt, cấp JWT Bearer token |
| **Mục 1** | Lưu họ tên, số điện thoại, email, số dư | Bảng `users` và `accounts`, truy xuất qua endpoint `GET /me` (và `GET /users/me`, `GET /accounts/me`) |
| **Mục 1** | Lịch sử giao dịch | `GET /history` và `GET /transactions` (sắp xếp giao dịch mới nhất lên đầu) |
| **Mục 1** | Chỉ người đã đăng nhập mới truy cập | Middleware / Dependency xác thực `get_current_user_id` kiểm tra token JWT hợp lệ và còn hạn |
| **Mục 2** | Thông tin người nộp tiền (họ tên, SĐT, email) tự động điền, chỉ đọc | Cung cấp dữ liệu đầy đủ từ `GET /me` |
| **Mục 2** | Số dư khả dụng của người nộp | Cung cấp trường `balance` trong `GET /me` và `GET /accounts/me` |
| **Mục 4** | Trừ tiền có điều kiện & mỗi txn_id trừ 1 lần | `POST /internal/accounts/debit` với câu lệnh SQL nguyên tử `WHERE balance >= :amount` và bảng `debit_ledger` |

---

## 3. Danh sách Endpoints (API Specification)

### 3.1. Public Endpoints (Client gọi qua API Gateway)

1. `POST /login` hoặc `POST /auth/login`
   - **Request Body**: `{"username": "alice", "password": "Password123!"}`
   - **Success (200)**:
     ```json
     {
       "access_token": "eyJhbGciOiJIUzI1NiIsIn...",
       "token_type": "bearer",
       "expires_in": 1800
     }
     ```
   - **Error (401)**: `{"detail": "Tên đăng nhập hoặc mật khẩu không chính xác"}`

2. `GET /me` hoặc `GET /users/me`
   - **Headers**: `Authorization: Bearer <token>` hoặc `X-User-Id: <uuid>` (do Gateway gán)
   - **Success (200)**:
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
   - **Error (401)**: `{"detail": "Yêu cầu đăng nhập để truy cập tài nguyên này"}`

3. `GET /accounts/me`
   - **Success (200)**: `{"balance": "30000000.00"}`

4. `GET /history` hoặc `GET /transactions`
   - **Success (200)**: Danh sách lịch sử giao dịch (mới nhất xếp trước)

### 3.2. Internal Endpoints (Nội bộ giữa các dịch vụ)

1. `GET /internal/users/{user_id}`
   - Cung cấp thông tin liên hệ của người nộp (họ tên, email) cho `payment-service` và `otp-service`.

2. `POST /internal/accounts/debit`
   - **Request Body**: `{"user_id": "...", "amount": 15000000.00, "transaction_id": "txn-uuid"}`
   - **Success (200)**:
     ```json
     {
       "success": true,
       "transaction_id": "txn-uuid",
       "balance_after": "15000000.00",
       "message": "Trừ tiền tài khoản thành công"
     }
     ```
   - **Error (422)**: `{"detail": "Số dư tài khoản không đủ để thực hiện thanh toán"}`

---

## 4. Kiểm thử và chạy ứng dụng

### Chạy Unit Test:
```bash
pytest backend/services/user-service/tests -v
```

### Chạy trực tiếp service:
```bash
uvicorn app.main:app --port 8000 --reload
```
Tài liệu tương tác Swagger UI: http://localhost:8000/docs
