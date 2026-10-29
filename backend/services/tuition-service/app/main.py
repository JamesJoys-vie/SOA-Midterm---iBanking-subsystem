"""Main entry point của tuition-service (FastAPI).

Thực hiện các nhiệm vụ của Hiệu trong Task 2:
- Tra cứu học phí theo MSSV: GET /tuitions?mssv= và GET /tuitions/{student_id}.
  Tự động trả về họ tên sinh viên và toàn bộ số tiền học phí (không nộp một phần).
- Khóa học phí (Reserve hold): POST /internal/tuitions/{id}/reserve (cập nhật có điều kiện).
- Đánh dấu đã thanh toán (Mark-paid): POST /internal/tuitions/{id}/commit.
- Mở khóa học phí (Release): POST /internal/tuitions/{id}/release.
"""
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import db_is_up, get_db, init_db
from app.schemas import (
    CommitRequest,
    CommitResponse,
    ReleaseRequest,
    ReleaseResponse,
    ReserveRequest,
    TuitionInfo,
)
from app.service import (
    commit_tuition,
    lookup_tuition,
    release_tuition,
    reserve_tuition,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("tuition-service")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Khởi động ứng dụng: Tự động khởi tạo bảng dữ liệu nếu chưa có."""
    log.info("tuition-service đang khởi động...")
    init_db()
    yield
    log.info("tuition-service đang tắt...")


app = FastAPI(
    title="Tuition Service - iBanking Subsystem",
    description="Dịch vụ tra cứu học phí theo MSSV, khóa học phí có điều kiện và cập nhật trạng thái thanh toán",
    version="1.0.0",
    lifespan=lifespan,
)


# ==============================================================================
# HEALTHCHECK & READINESS ENDPOINTS
# ==============================================================================

@app.get("/health", tags=["Hệ thống"])
def health() -> dict:
    """Liveness check: Xác nhận tiến trình service đang chạy."""
    return {"status": "ok", "service": "tuition-service"}


@app.get("/ready", tags=["Hệ thống"])
def ready() -> JSONResponse:
    """Readiness check: Xác nhận service đã kết nối thành công tới database."""
    if db_is_up():
        return JSONResponse({"status": "ready", "service": "tuition-service"})
    return JSONResponse(
        {"status": "database unavailable", "service": "tuition-service"},
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    )


# ==============================================================================
# TASK 2: TRA CỨU HỌC PHÍ (GET /tuitions?mssv= và GET /tuitions/{student_id})
# ==============================================================================

@app.get(
    "/tuitions",
    response_model=TuitionInfo,
    tags=["Tra cứu học phí"],
    summary="Tra cứu học phí theo MSSV qua query parameter (?mssv=)",
)
def get_tuition_by_query(
    mssv: Optional[str] = Query(None, description="Mã số sinh viên (ví dụ: 52100001, 521H0081)"),
    student_id: Optional[str] = Query(None, description="Alias cho mssv"),
    db: Session = Depends(get_db),
) -> TuitionInfo:
    """Yêu cầu Mục 2b trong Phân công công việc:

    'Nhập MSSV -> tự động tra cứu tên sinh viên và số tiền'.
    'Chỉ thanh toán toàn bộ, không thanh toán một phần'.
    """
    code = mssv or student_id
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vui lòng cung cấp tham số 'mssv' để tra cứu",
        )
    return lookup_tuition(db, code)


@app.get(
    "/tuitions/{student_id}",
    response_model=TuitionInfo,
    tags=["Tra cứu học phí"],
    summary="Tra cứu học phí theo MSSV qua path parameter (chuẩn OpenAPI)",
)
def get_tuition_by_path(
    student_id: str,
    db: Session = Depends(get_db),
) -> TuitionInfo:
    """Tra cứu học phí của sinh viên theo đường dẫn /tuitions/{student_id}."""
    return lookup_tuition(db, student_id)


# ==============================================================================
# TASK 2: KHÓA HỌC PHÍ CÓ ĐIỀU KIỆN (RESERVE HOLD)
# ==============================================================================

@app.post(
    "/internal/tuitions/{tuition_id}/reserve",
    response_model=TuitionInfo,
    tags=["Khóa học phí"],
    summary="Khóa học phí có điều kiện cho một giao dịch (chuẩn internal)",
)
@app.post(
    "/tuitions/{tuition_id}/reserve",
    response_model=TuitionInfo,
    tags=["Khóa học phí"],
    summary="Khóa học phí có điều kiện cho một giao dịch (alias)",
)
def reserve_tuition_endpoint(
    tuition_id: str,
    body: ReserveRequest,
    db: Session = Depends(get_db),
) -> TuitionInfo:
    """Yêu cầu Mục 2 trong Phân công công việc:

    'Endpoint khóa học phí (cập nhật có điều kiện)'.
    Thực hiện câu lệnh UPDATE có điều kiện nguyên tử để khóa học phí trong 10 phút,
    chống tranh chấp đồng thời khi nhiều người cùng nộp một mã sinh viên.
    """
    return reserve_tuition(db, tuition_id, body.transaction_id)


# ==============================================================================
# TASK 4 & TÓM TẮT: ĐÁNH DẤU ĐÃ THANH TOÁN (MARK-PAID / COMMIT)
# ==============================================================================

@app.post(
    "/internal/tuitions/{tuition_id}/commit",
    response_model=CommitResponse,
    tags=["Cập nhật học phí"],
    summary="Cập nhật học phí thành đã thanh toán (chỉ giao dịch đang giữ khóa)",
)
@app.post(
    "/tuitions/{tuition_id}/commit",
    response_model=CommitResponse,
    tags=["Cập nhật học phí"],
    summary="Cập nhật học phí thành đã thanh toán (alias)",
)
def commit_tuition_endpoint(
    tuition_id: str,
    body: CommitRequest,
    db: Session = Depends(get_db),
) -> CommitResponse:
    """Yêu cầu Mục 4 và tóm tắt công việc của Hiệu:

    'mark-paid (chỉ giao dịch đang giữ khóa)'.
    Chuyển trạng thái học phí sang PAID. Chỉ chấp nhận nếu giao dịch hiện tại đang giữ khóa hợp lệ.
    """
    return commit_tuition(db, tuition_id, body.transaction_id)


# ==============================================================================
# TASK 4: MỞ KHÓA HỌC PHÍ (RELEASE HOLD KHI HỦY HOẶC THẤT BẠI)
# ==============================================================================

@app.post(
    "/internal/tuitions/{tuition_id}/release",
    response_model=ReleaseResponse,
    tags=["Mở khóa học phí"],
    summary="Mở khóa học phí đưa về trạng thái UNPAID",
)
@app.post(
    "/tuitions/{tuition_id}/release",
    response_model=ReleaseResponse,
    tags=["Mở khóa học phí"],
    summary="Mở khóa học phí (alias)",
)
def release_tuition_endpoint(
    tuition_id: str,
    body: ReleaseRequest,
    db: Session = Depends(get_db),
) -> ReleaseResponse:
    """Giải phóng khóa học phí khi giao dịch bị hủy bỏ hoặc thất bại."""
    return release_tuition(db, tuition_id, body.transaction_id)
