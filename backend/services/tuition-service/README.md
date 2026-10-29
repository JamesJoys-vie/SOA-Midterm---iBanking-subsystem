# tuition-service

Dịch vụ tra cứu học phí và quản lý trạng thái thanh toán cho phân hệ iBanking.
Thành viên phụ trách: **Nguyễn Đức Hiệu (524H0087)**.

---

## 1. Vị trí trong kiến trúc hệ thống

```
Trình duyệt ──> API Gateway ──> tuition-service ──> tuition database (riêng)
                                        ^
                                        |
                              payment-service gọi các
                              endpoint /internal/* để
                              khóa / xác nhận / mở khóa
```

- **Cơ sở dữ liệu độc lập**: `tuition-service` sở hữu riêng 2 bảng `students` và `tuitions`. Không service nào được truy cập trực tiếp vào DB này.
- **Atomic Conditional Update**: Toàn bộ thao tác thay đổi trạng thái học phí đều dùng `UPDATE ... WHERE status = 'X'` một lần duy nhất. Cơ sở dữ liệu (MySQL InnoDB) tự xử lý lock ở mức hàng, đảm bảo khi 2 người cùng thanh toán cho 1 sinh viên, chỉ 1 người thắng.
- **Idempotent**: Cùng một `transaction_id` có thể gọi `reserve` nhiều lần (gia hạn khóa) và `commit` nhiều lần (trả về PAID) mà không gây lỗi.

---

## 2. Đáp ứng các yêu cầu trong bảng "Phân công công việc"

| Mục | Yêu cầu nghiệp vụ | Triển khai trong tuition-service |
|---|---|---|
| **Task 2** | Nhập MSSV → tự động tra cứu họ tên sinh viên và số tiền | `GET /tuitions/{student_id}` và `GET /tuitions?mssv=` |
| **Task 2** | Chỉ thanh toán toàn bộ, không thanh toán một phần | Endpoint trả về `amount` cố định của kỳ học, không cho nhập số tiền tùy ý |
| **Task 2** | Ưu tiên kỳ cũ nhất chưa nộp trước | `ORDER BY paid_priority ASC, term ASC` |
| **Task 2** | Khóa học phí (endpoint reserve có điều kiện) | `POST /internal/tuitions/{id}/reserve` dùng `UPDATE WHERE status='UNPAID'` |
| **Task 4** | Mark-paid (chỉ giao dịch đang giữ khóa) | `POST /internal/tuitions/{id}/commit` dùng `UPDATE WHERE status='RESERVED' AND reserved_by_txn=txn_id` |
| **Task 4** | Mở khóa khi hủy giao dịch | `POST /internal/tuitions/{id}/release` |

---

## 3. Sơ đồ trạng thái học phí

```
UNPAID ──[reserve txn-A]──> RESERVED(by txn-A)
                                │
                    ┌───────────┴──────────────┐
                    │                          │
             [commit txn-A]            [release txn-A]
                    │                  (hủy / thất bại)
                    ▼                          │
                  PAID                      UNPAID <──┘
```

---

## 4. Danh sách Endpoints (API Specification)

### 4.1. Public Endpoints (Client gọi qua API Gateway)

1. `GET /tuitions/{student_id}` hoặc `GET /tuitions?mssv={mssv}`
   - **Success (200)**:
     ```json
     {
       "tuition_id": "uuid-...",
       "student_id": "52100001",
       "student_name": "Pham Minh D",
       "term": "2025-HK1",
       "amount": "15000000.00",
       "status": "UNPAID"
     }
     ```
   - **Error (404)**: `{"detail": "Không tìm thấy sinh viên có MSSV '...'"}`

### 4.2. Internal Endpoints (payment-service gọi trực tiếp, không qua Gateway)

2. `POST /internal/tuitions/{tuition_id}/reserve`
   - **Request Body**: `{"transaction_id": "txn-uuid"}`
   - **Success (200)**: `TuitionInfo` với `status: "RESERVED"`
   - **Error (409)**: `{"detail": "Học phí đang được một giao dịch khác giữ khóa..."}`

3. `POST /internal/tuitions/{tuition_id}/commit`
   - **Request Body**: `{"transaction_id": "txn-uuid"}`
   - **Success (200)**: `{"status": "PAID", "message": "..."}`
   - **Error (409)**: Nếu học phí không được khóa bởi giao dịch này

4. `POST /internal/tuitions/{tuition_id}/release`
   - **Request Body**: `{"transaction_id": "txn-uuid"}`
   - **Success (200)**: `{"released": true/false, "message": "..."}`

---

## 5. Kiểm thử và chạy ứng dụng

### Chạy Unit Test (23 test cases):
```bash
pytest backend/services/tuition-service/tests -v
```

### Chạy trực tiếp service:
```bash
cd backend/services/tuition-service
uvicorn app.main:app --port 8001 --reload
```
Swagger UI: http://localhost:8001/docs
