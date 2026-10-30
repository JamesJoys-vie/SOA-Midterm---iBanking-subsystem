"""Test setup: SQLite file DB + in-memory fakes of user / tuition / otp services (no network, no Docker).

Run from backend/services/payment_service:   python -m pytest -q tests
The fakes copy the real rules: conditional debit (balance >= amount, once per txn), conditional reserve /
commit / release, single-use OTP. A lock makes each fake call atomic like one SQL UPDATE.
"""
import os
import sys
import threading
from decimal import Decimal
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
for p in (SERVICE_DIR, SERVICE_DIR.parents[1]):  # app/ and backend/ (for shared/)
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))
os.environ.setdefault("RUN_WORKERS", "false")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.clients.base import UpstreamRejected, UpstreamUnavailable
from app.clients.otp_client import OtpCheck
from app.clients.tuition_client import PAID, RESERVED, UNPAID, Tuition
from app.clients.user_client import Payer
from app.domain.models import Base
from app.domain.payment_saga import PaymentSaga
from app.repositories.transaction_repo import TransactionRepository


class FakeUsers:
    name = "user-service"

    def __init__(self):
        self.lock = threading.Lock()
        self.balances = {"u1": Decimal("20000000"), "u2": Decimal("20000000"), "poor": Decimal("1000")}
        self.debits, self.credits, self.history = {}, {}, []
        self.refund_supported = True

    def get_payer(self, user_id):
        if user_id not in self.balances:
            raise UpstreamRejected(self.name, 404, "User not found")
        return Payer(user_id, f"Name {user_id}", f"{user_id}@example.com", "0900", self.balances[user_id])

    def debit(self, user_id, amount, txn_id):
        with self.lock:
            if txn_id in self.debits:
                return self.balances[user_id]
            if self.balances[user_id] < amount:
                raise UpstreamRejected(self.name, 422, "Insufficient balance")
            self.balances[user_id] -= amount
            self.debits[txn_id] = amount
            return self.balances[user_id]

    def refund(self, user_id, amount, txn_id):
        if not self.refund_supported:
            raise UpstreamRejected(self.name, 404, "Not Found")
        with self.lock:
            if txn_id not in self.credits:
                self.balances[user_id] += amount
                self.credits[txn_id] = amount
            return self.balances[user_id]

    def record_history(self, user_id, student_id, tuition_id, amount, status, failure_reason):
        self.history.append((user_id, student_id, status))


class FakeTuitions:
    name = "tuition-service"

    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {"S1": {"id": "t1", "amount": Decimal("15000000"), "status": UNPAID, "by": None},
                     "S2": {"id": "t2", "amount": Decimal("12000000"), "status": UNPAID, "by": None},
                     "S3": {"id": "t3", "amount": Decimal("5000000"), "status": PAID, "by": "old"}}
        self.commit_fails = False

    def _row(self, tuition_id):
        return next(r for r in self.rows.values() if r["id"] == tuition_id)

    def _info(self, mssv, r):
        return Tuition(r["id"], mssv, "Student", "2025-HK1", r["amount"], r["status"])

    def lookup(self, mssv):
        if mssv not in self.rows:
            raise UpstreamRejected(self.name, 404, "Student not found")
        return self._info(mssv, self.rows[mssv])

    def reserve(self, tuition_id, txn_id):
        with self.lock:
            r = self._row(tuition_id)
            if r["status"] == UNPAID or (r["status"] == RESERVED and r["by"] == txn_id):
                r["status"], r["by"] = RESERVED, txn_id
                return self._info("?", r)
            raise UpstreamRejected(self.name, 409, "Tuition held by another transaction or paid")

    def commit(self, tuition_id, txn_id):
        with self.lock:
            r = self._row(tuition_id)
            if self.commit_fails:
                raise UpstreamRejected(self.name, 409, "Not reserved by this transaction")
            if r["status"] == PAID and r["by"] == txn_id:
                return
            if r["status"] != RESERVED or r["by"] != txn_id:
                raise UpstreamRejected(self.name, 409, "Not reserved by this transaction")
            r["status"] = PAID

    def release(self, tuition_id, txn_id):
        with self.lock:
            r = self._row(tuition_id)
            if r["status"] == RESERVED and r["by"] == txn_id:
                r["status"], r["by"] = UNPAID, None
                return True
            return False


class FakeOtps:
    name = "otp-service"

    def __init__(self):
        self.lock = threading.Lock()
        self.codes = {}
        self.down = False

    def issue(self, txn_id, email, full_name):
        if self.down:
            raise UpstreamUnavailable("otp-service is unavailable")
        self.codes[txn_id] = "123456"
        return 300

    def verify(self, txn_id, code):
        with self.lock:
            if self.codes.get(txn_id) == code:
                del self.codes[txn_id]  # single use
                return OtpCheck(True)
            return OtpCheck(False, "invalid" if txn_id in self.codes else "expired", 4)


@pytest.fixture
def env(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'payments.db'}", connect_args={"timeout": 30,
                                                                                    "check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    users, tuitions, otps = FakeUsers(), FakeTuitions(), FakeOtps()

    def new_saga():
        """One saga = one DB session (one per thread in concurrency tests)."""
        return PaymentSaga(TransactionRepository(factory()), users, tuitions, otps)

    yield type("Env", (), {"saga": new_saga(), "new_saga": staticmethod(new_saga), "users": users,
                           "tuitions": tuitions, "otps": otps, "factory": factory})
    engine.dispose()
