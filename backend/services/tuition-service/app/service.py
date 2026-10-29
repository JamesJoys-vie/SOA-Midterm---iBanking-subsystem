"""Tầng xử lý nghiệp vụ (Business Service Layer) cho tuition-service.

Triển khai các yêu cầu của Task 2:
- Tra cứu học phí theo MSSV: tự động tìm họ tên sinh viên và số tiền.
- Quy tắc: Trả về toàn bộ số tiền học phí (không thanh toán một phần).
- Khóa học phí (Reserve/Hold) bằng câu lệnh UPDATE có điều kiện nguyên tử (Atomic Conditional Update)
  để phòng tránh Race Condition khi có 2 người cùng nộp học phí cho một sinh viên.
- Đánh dấu đã thanh toán (mark-paid / commit): Chỉ giao dịch đang giữ khóa mới được commit sang PAID.
- Mở khóa (Release): Nhả trạng thái về UNPAID khi giao dịch bị hủy hoặc thất bại.
"""
import logging
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PAID, RESERVED, UNPAID, Student, Tuition, utcnow
from app.schemas import CommitResponse, ReleaseResponse, TuitionInfo

log = logging.getLogger("tuition-service.service")


def lookup_tuition(db: Session, mssv: str) -> TuitionInfo:
    """Tra cứu thông tin học phí của sinh viên theo MSSV.

    Quy tắc nghiệp vụ:
    1. So khớp MSSV không phân biệt chữ hoa / thường (ví dụ: 521h0081 khớp với 521H0081).
    2. Ưu tiên học kỳ chưa thanh toán (UNPAID) cũ nhất trước.
    3. Nếu học phí đang bị giữ khóa (RESERVED) nhưng đã quá hạn (reserved_until < now),
       hệ thống tự động hiển thị trạng thái là UNPAID để người dùng có thể tiếp tục thanh toán.
    4. Nếu tất cả các kỳ đều đã thanh toán, trả về học kỳ gần nhất với trạng thái PAID
       để giao diện thông báo 'học phí đã được thanh toán toàn bộ'.
    5. Luôn trả về toàn bộ số tiền học phí (không có tính năng nộp một phần).
    """
    clean_mssv = mssv.strip().upper()
    if not clean_mssv:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mã số sinh viên (MSSV) không được để trống",
        )

    # 1. Tìm thông tin sinh viên
    student = db.scalar(
        select(Student).where(func.upper(Student.student_id) == clean_mssv)
    )
    if not student:
        log.warning("Không tìm thấy sinh viên có MSSV='%s'", clean_mssv)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy sinh viên có MSSV '{clean_mssv}'",
        )

    # 2. Tìm danh sách học phí của sinh viên này
    now = utcnow()
    # Ưu tiên các kỳ chưa PAID xếp trước, sắp xếp kỳ học tăng dần (kỳ cũ trước)
    paid_priority = case((Tuition.status == PAID, 1), else_=0)
    tuition = db.scalars(
        select(Tuition)
        .where(Tuition.student_id == student.student_id)
        .order_by(paid_priority, Tuition.term.asc())
    ).first()

    if not tuition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Sinh viên '{student.full_name}' ({student.student_id}) không có dữ liệu học phí",
        )

    # Nếu tất cả các kỳ đều đã PAID -> lấy kỳ mới nhất để hiển thị
    if tuition.status == PAID:
        tuition = db.scalars(
            select(Tuition)
            .where(Tuition.student_id == student.student_id)
            .order_by(Tuition.term.desc())
        ).first()

    # 3. Xác định trạng thái hiển thị
    display_status = tuition.status
    if display_status == RESERVED and tuition.reserved_until and tuition.reserved_until < now:
        # Khóa đã quá hạn -> Xem như UNPAID để người nộp có thể thanh toán tiếp
        display_status = UNPAID

    return TuitionInfo(
        tuition_id=tuition.id,
        student_id=tuition.student_id,
        student_name=student.full_name,
        term=tuition.term,
        amount=tuition.amount,
        status=display_status,
    )


def reserve_tuition(
    db: Session,
    tuition_id: str,
    transaction_id: str,
) -> TuitionInfo:
    """Khóa giữ chỗ học phí (Reserve/Hold) cho một giao dịch đang thực hiện.

    Sử dụng câu lệnh UPDATE có điều kiện nguyên tử (Atomic Conditional Update)
    ở mức Database Engine. Cơ chế này đảm bảo khi có nhiều giao dịch cùng tranh chấp
    thanh toán cho 1 học phí, chỉ duy nhất 1 giao dịch thành công (rowcount == 1).
    Giao dịch còn lại sẽ thấy rowcount == 0 và bị từ chối với mã lỗi 409 Conflict.

    Tính Idempotent: Nếu cùng một transaction_id gọi lại (ví dụ khi gửi lại mã OTP),
    lệnh sẽ tự động gia hạn thời gian giữ chỗ mà không báo lỗi.
    """
    now = utcnow()
    expiry = now + timedelta(seconds=settings.reservation_ttl_seconds)

    # Câu lệnh cập nhật có điều kiện nguyên tử
    res = db.execute(
        update(Tuition)
        .where(
            Tuition.id == tuition_id,
            or_(
                Tuition.status == UNPAID,
                and_(
                    Tuition.status == RESERVED,
                    or_(
                        Tuition.reserved_until < now,       # Khóa cũ của giao dịch khác đã hết hạn
                        Tuition.reserved_by_txn == transaction_id,  # Cùng giao dịch gọi lại (gia hạn)
                    ),
                ),
            ),
        )
        .values(
            status=RESERVED,
            reserved_by_txn=transaction_id,
            reserved_until=expiry,
            version=Tuition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    tuition = db.get(Tuition, tuition_id)
    if not tuition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy khoản học phí",
        )

    # Nếu rowcount == 0: Không khóa được vì điều kiện WHERE không khớp
    if res.rowcount != 1:
        if tuition.status == PAID:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Khoản học phí này đã được thanh toán",
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Học phí đang được một giao dịch khác giữ khóa để thanh toán",
            )

    student = db.get(Student, tuition.student_id)
    student_name = student.full_name if student else "N/A"

    log.info(
        "Khóa học phí thành công: tuition_id=%s, txn_id=%s, hạn khóa đến: %s",
        tuition_id,
        transaction_id,
        expiry,
    )

    return TuitionInfo(
        tuition_id=tuition.id,
        student_id=tuition.student_id,
        student_name=student_name,
        term=tuition.term,
        amount=tuition.amount,
        status=RESERVED,
    )


def commit_tuition(
    db: Session,
    tuition_id: str,
    transaction_id: str,
) -> CommitResponse:
    """Đánh dấu học phí đã được thanh toán thành công (Mark-paid).

    Quy tắc an toàn:
    - Chỉ giao dịch đang giữ khóa (status='RESERVED' AND reserved_by_txn=transaction_id)
      mới được phép chuyển trạng thái học phí sang 'PAID'.
    - Khi chuyển sang PAID, xóa thông tin reserved_until và lưu paid_by_txn.
    - Idempotent: Nếu đã PAID bởi cùng transaction_id này, trả về thành công mà không gây lỗi.
    """
    # Kiểm tra Idempotency TRƯỚC: Nếu đã PAID bởi chính transaction_id này thì trả về luôn
    # (Không cần chạy UPDATE nữa, tránh lỗi khi gọi lại sau khi đã commit)
    tuition = db.get(Tuition, tuition_id, populate_existing=True)
    if not tuition:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy khoản học phí")

    if tuition.status == PAID and tuition.paid_by_txn == transaction_id:
        log.info(
            "Commit idempotent: tuition_id=%s đã PAID bởi txn_id=%s từ trước", tuition_id, transaction_id
        )
        return CommitResponse(status=PAID, message="Học phí đã được thanh toán bởi giao dịch này trước đó")

    # Thực hiện UPDATE có điều kiện nguyên tử: chỉ thành công khi RESERVED bởi đúng txn_id này
    res = db.execute(
        update(Tuition)
        .where(
            Tuition.id == tuition_id,
            Tuition.status == RESERVED,
            Tuition.reserved_by_txn == transaction_id,
        )
        .values(
            status=PAID,
            paid_by_txn=transaction_id,
            reserved_until=None,
            version=Tuition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if res.rowcount == 1:
        log.info("Xác nhận mark-paid thành công: tuition_id=%s bởi txn_id=%s", tuition_id, transaction_id)
        return CommitResponse(status=PAID, message="Học phí đã được đánh dấu thanh toán thành công")

    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Học phí không được khóa bởi giao dịch này hoặc đã được thanh toán bởi giao dịch khác",
    )


def release_tuition(
    db: Session,
    tuition_id: str,
    transaction_id: str,
) -> ReleaseResponse:
    """Mở khóa học phí (Release hold) đưa trạng thái trở lại 'UNPAID'.

    Được gọi khi người dùng bấm Hủy giao dịch hoặc khi các bước tiếp theo của Saga
    gặp sự cố (ví dụ: OTP sai quá số lần, trừ tiền tài khoản thất bại).
    """
    res = db.execute(
        update(Tuition)
        .where(
            Tuition.id == tuition_id,
            Tuition.status == RESERVED,
            Tuition.reserved_by_txn == transaction_id,
        )
        .values(
            status=UNPAID,
            reserved_by_txn=None,
            reserved_until=None,
            version=Tuition.version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()

    if res.rowcount == 1:
        log.info("Giải phóng khóa học phí thành công: tuition_id=%s cho txn_id=%s", tuition_id, transaction_id)
        return ReleaseResponse(released=True, message="Đã mở khóa học phí thành công")

    return ReleaseResponse(
        released=False,
        message="Khóa học phí không tồn tại hoặc không thuộc về giao dịch này",
    )
