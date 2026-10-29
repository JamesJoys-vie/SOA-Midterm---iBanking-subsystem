"""Tầng xử lý nghiệp vụ (Business Service Layer) cho user-service.

Triển khai chi tiết các yêu cầu của Task 1 và Task 2:
- Xác thực đăng nhập và cấp phát JWT token.
- Truy xuất thông tin người dùng và số dư khả dụng (GET /me).
- Trừ tiền tài khoản có điều kiện nguyên tử (balance >= amount) và đảm bảo Idempotency.
- Quản lý và tra cứu lịch sử giao dịch người dùng (GET /history).
"""
import logging
from decimal import Decimal
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Account, DebitLedger, TransactionHistory, User, utcnow
from app.schemas import (
    DebitResponse,
    TokenResponse,
    TransactionHistoryItem,
    UserProfile,
)
from app.security import _DUMMY_HASH, create_access_token, verify_password

log = logging.getLogger("user-service.service")


def authenticate_user(db: Session, username: str, password: str) -> TokenResponse:
    """Xác thực người dùng bằng tên đăng nhập và mật khẩu.

    Sử dụng bcrypt để so khớp mật khẩu và kỹ thuật dummy-hash để chống timing attack.
    Khi thành công, cấp phát JWT Bearer Token với thời hạn cấu hình.
    """
    user = db.scalar(select(User).where(User.username == username.strip()))

    # Lấy hash đã lưu nếu user tồn tại, nếu không dùng _DUMMY_HASH để thời gian xử lý đồng đều
    hash_to_check = user.password_hash if user else _DUMMY_HASH
    is_valid_password = verify_password(password, hash_to_check)

    if not user or not is_valid_password:
        log.warning("Đăng nhập thất bại cho username='%s'", username)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tên đăng nhập hoặc mật khẩu không chính xác",
        )

    # Sinh mã JWT token
    token = create_access_token(
        user_id=user.id,
        secret=settings.jwt_secret,
        expire_minutes=settings.jwt_expire_minutes,
    )

    log.info("Người dùng '%s' (id=%s) đã đăng nhập thành công", user.username, user.id)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.jwt_expire_minutes * 60,
    )


def get_user_profile(db: Session, user_id: str) -> UserProfile:
    """Truy xuất thông tin người dùng và số dư khả dụng hiện tại (GET /me).

    Nếu tài khoản ngân hàng chưa tồn tại, tự động khởi tạo với số dư 0.
    """
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy người dùng",
        )

    # Tìm tài khoản ngân hàng liên kết
    account = db.scalar(select(Account).where(Account.user_id == user.id))
    if not account:
        # Tự động tạo tài khoản mới nếu chưa có
        account = Account(user_id=user.id, balance=Decimal("0.00"), version=0)
        db.add(account)
        db.commit()
        db.refresh(account)

    return UserProfile(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        balance=account.balance,
    )


def get_account_balance(db: Session, user_id: str) -> Decimal:
    """Truy xuất nhanh số dư khả dụng của người dùng."""
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài khoản thanh toán của người dùng này",
        )
    return account.balance


def debit_user_account(
    db: Session,
    user_id: str,
    amount: Decimal,
    transaction_id: str,
) -> DebitResponse:
    """Thực hiện trừ tiền có điều kiện nguyên tử khỏi tài khoản người nộp.

    Quy tắc nghiệp vụ:
    1. Idempotency: Mỗi transaction_id chỉ trừ tiền đúng 1 lần duy nhất.
       Nếu đã trừ trước đó, trả về thành công kèm số dư hiện tại mà không trừ lần 2.
    2. Điều kiện đủ số dư: Cập nhật nguyên tử với mệnh đề 'WHERE balance >= :amount'.
       Nếu số dư không đủ -> ném HTTP 422 Unprocessable Entity.
    """
    # 1. Kiểm tra Idempotency qua bảng DebitLedger
    existing_ledger = db.scalar(
        select(DebitLedger).where(DebitLedger.transaction_id == transaction_id)
    )
    if existing_ledger:
        log.info(
            "Yêu cầu trừ tiền bị lặp cho txn_id=%s, trả về kết quả trước đó mà không trừ lại",
            transaction_id,
        )
        return DebitResponse(
            success=True,
            transaction_id=transaction_id,
            balance_after=existing_ledger.balance_after,
            message="Giao dịch này đã được ghi nhận trừ tiền trước đó",
        )

    # 2. Tìm tài khoản người nộp
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Không tìm thấy tài khoản ngân hàng của người dùng",
        )

    # 3. Thực hiện câu lệnh UPDATE có điều kiện nguyên tử (Atomic Conditional Update)
    result = db.execute(
        update(Account)
        .where(Account.user_id == user_id, Account.balance >= amount)
        .values(
            balance=Account.balance - amount,
            version=Account.version + 1,
        )
        .execution_options(synchronize_session=False)
    )

    # Nếu rowcount == 0: nghĩa là số dư nhỏ hơn số tiền cần trừ
    if result.rowcount == 0:
        log.warning(
            "Trừ tiền thất bại cho user_id=%s: Số dư khả dụng (%s) nhỏ hơn số tiền (%s)",
            user_id,
            account.balance,
            amount,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Số dư tài khoản không đủ để thực hiện thanh toán",
        )

    # Lấy lại số dư mới sau khi trừ
    db.refresh(account)
    new_balance = account.balance

    # 4. Ghi nhận vào sổ cái DebitLedger để bảo đảm Idempotency
    ledger = DebitLedger(
        transaction_id=transaction_id,
        account_id=account.id,
        amount=amount,
        balance_after=new_balance,
    )
    db.add(ledger)
    db.commit()

    log.info(
        "Trừ tiền thành công: user_id=%s, txn_id=%s, trừ %s VND, số dư còn lại: %s VND",
        user_id,
        transaction_id,
        amount,
        new_balance,
    )

    return DebitResponse(
        success=True,
        transaction_id=transaction_id,
        balance_after=new_balance,
        message="Trừ tiền tài khoản thành công",
    )


def get_transaction_history(
    db: Session,
    user_id: str,
    limit: int = 100,
) -> List[TransactionHistoryItem]:
    """Lấy danh sách lịch sử giao dịch của người dùng hiện tại (mới nhất lên đầu)."""
    transactions = db.scalars(
        select(TransactionHistory)
        .where(TransactionHistory.payer_user_id == user_id)
        .order_by(TransactionHistory.created_at.desc())
        .limit(limit)
    ).all()

    return [TransactionHistoryItem.model_validate(t) for t in transactions]


def record_transaction_history(
    db: Session,
    user_id: str,
    student_id: str,
    tuition_id: Optional[str],
    amount: Decimal,
    status: str = "SUCCESS",
    failure_reason: Optional[str] = None,
) -> TransactionHistory:
    """Ghi lại lịch sử giao dịch thanh toán."""
    account = db.scalar(select(Account).where(Account.user_id == user_id))
    account_id = account.id if account else "unknown-account"

    history_record = TransactionHistory(
        account_id=account_id,
        payer_user_id=user_id,
        student_id=student_id,
        tuition_id=tuition_id,
        amount=amount,
        status=status,
        failure_reason=failure_reason,
        completed_at=utcnow() if status == "SUCCESS" else None,
    )
    db.add(history_record)
    db.commit()
    db.refresh(history_record)
    return history_record
