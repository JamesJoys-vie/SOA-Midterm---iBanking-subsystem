"""All SQL of payments_db. Status changes are conditional UPDATEs (compare-and-set):

    UPDATE transactions SET status = :to WHERE id = :id AND status IN (:from)

The database runs that statement atomically, so when two requests race (double click on "Confirm",
two service replicas) exactly one gets rowcount == 1 and continues; the other one stops.
"""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.domain.models import OutboxEvent, Transaction, TxnStatus, utcnow

MAX_HISTORY = 100


class TransactionRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- read ----------------
    def get(self, txn_id: str) -> Transaction | None:
        return self.db.get(Transaction, txn_id, populate_existing=True)  # always re-read, never a stale copy

    def get_owned(self, txn_id: str, user_id: str) -> Transaction | None:
        txn = self.get(txn_id)
        return txn if txn and txn.payer_user_id == user_id else None

    def find_by_key(self, idempotency_key: str) -> Transaction | None:
        return self.db.scalar(select(Transaction).where(Transaction.idempotency_key == idempotency_key))

    def list_by_user(self, user_id: str, limit: int = MAX_HISTORY) -> list[Transaction]:
        return list(self.db.scalars(select(Transaction).where(Transaction.payer_user_id == user_id)
                                    .order_by(Transaction.created_at.desc()).limit(limit)))

    def find_expired_pending(self, now: datetime, limit: int = 50) -> list[Transaction]:
        return list(self.db.scalars(select(Transaction).where(Transaction.status == TxnStatus.PENDING_OTP.value,
                                                              Transaction.expires_at < now).limit(limit)))

    def find_stuck_processing(self, older_than: datetime, limit: int = 50) -> list[Transaction]:
        return list(self.db.scalars(select(Transaction).where(Transaction.status == TxnStatus.PROCESSING.value,
                                                              Transaction.updated_at < older_than).limit(limit)))

    def find_pending_refunds(self, limit: int = 50) -> list[Transaction]:
        return list(self.db.scalars(select(Transaction).where(Transaction.needs_refund.is_(True)).limit(limit)))

    # ---------------- write ----------------
    def create(self, txn: Transaction) -> Transaction | None:
        """Insert; None when the Idempotency-Key already exists (a parallel request with the same key won).
        """
        self.db.add(txn)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            return None
        return txn

    def transition(self, txn_id: str, from_status: TxnStatus | tuple[TxnStatus, ...], to_status: TxnStatus,
                   **fields) -> bool:
        """Atomic compare-and-set of the status. True only for the caller that made the change.
        """
        sources = from_status if isinstance(from_status, tuple) else (from_status,)
        res = self.db.execute(update(Transaction)
                              .where(Transaction.id == txn_id, Transaction.status.in_([s.value for s in sources]))
                              .values(status=to_status.value, updated_at=utcnow(), **fields)
                              .execution_options(synchronize_session=False))
        self.db.commit()
        return res.rowcount == 1

    def update_fields(self, txn_id: str, **fields) -> None:
        self.db.execute(update(Transaction).where(Transaction.id == txn_id)
                        .values(updated_at=utcnow(), **fields).execution_options(synchronize_session=False))
        self.db.commit()

    def mark_success(self, txn_id: str, balance_after: Decimal, event_type: str, event_payload: dict) -> bool:
        """PROCESSING -> SUCCESS and the outbox event in ONE database transaction (both or neither).
        """
        res = self.db.execute(update(Transaction)
                              .where(Transaction.id == txn_id, Transaction.status == TxnStatus.PROCESSING.value)
                              .values(status=TxnStatus.SUCCESS.value, balance_after=balance_after,
                                      completed_at=utcnow(), updated_at=utcnow(), failure_reason=None)
                              .execution_options(synchronize_session=False))
        if res.rowcount != 1:
            self.db.rollback()
            return False
        self.db.add(OutboxEvent(type=event_type, payload=event_payload))
        self.db.commit()
        return True
