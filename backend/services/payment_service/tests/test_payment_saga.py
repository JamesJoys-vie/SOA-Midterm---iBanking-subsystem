"""PaymentSaga against fakes: happy path, server-side checks, compensation and the two race conditions of the assignment."""
import threading
from datetime import timedelta
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.core.errors import BadRequest, Conflict, Gone, InsufficientBalance, UpstreamError
from app.domain.models import OutboxEvent, TxnStatus, utcnow
from app.workers.expiry_job import ExpiryJob

KEY = "key-0001-abcd"


def run_parallel(n, fn):
    """Start n threads at the same instant (barrier) and collect results / errors.
    """
    barrier, results = threading.Barrier(n), [None] * n

    def worker(i):
        barrier.wait()
        try:
            results[i] = fn(i)
        except Exception as e:  # noqa: BLE001
            results[i] = e
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# ---------------- section 2 -> 4: happy path ----------------
def test_full_payment_flow(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    assert txn.status == TxnStatus.PENDING_OTP.value
    assert txn.amount == Decimal("15000000")  # amount from tuition-service
    assert env.tuitions.rows["S1"]["status"] == "RESERVED"
    assert txn.id in env.otps.codes  # OTP bound to this transaction

    done = env.saga.confirm("u1", txn.id, "123456")
    assert done.status == TxnStatus.SUCCESS.value
    assert env.users.balances["u1"] == Decimal("5000000")
    assert done.balance_after == Decimal("5000000")
    assert env.tuitions.rows["S1"]["status"] == "PAID"
    assert ("u1", "S1", "SUCCESS") in env.users.history
    with env.factory() as db:
        event = db.scalar(select(OutboxEvent))
    assert event.type == "payment.completed" and event.payload["transaction_id"] == txn.id


def test_same_idempotency_key_returns_same_transaction(env):
    first = env.saga.initiate("u1", "S1", KEY)
    assert env.saga.initiate("u1", "S1", KEY).id == first.id
    with pytest.raises(Conflict):
        env.saga.initiate("u2", "S1", KEY)  # key of another user


def test_bad_idempotency_key(env):
    with pytest.raises(BadRequest):
        env.saga.initiate("u1", "S1", "short")


# ---------------- section 2: server-side checks ----------------
def test_insufficient_balance_is_rejected_before_any_hold(env):
    with pytest.raises(InsufficientBalance):
        env.saga.initiate("poor", "S1", KEY)
    assert env.tuitions.rows["S1"]["status"] == "UNPAID"


def test_paid_tuition_is_rejected(env):
    with pytest.raises(Conflict):
        env.saga.initiate("u1", "S3", KEY)


def test_otp_send_failure_releases_the_tuition(env):
    env.otps.down = True
    with pytest.raises(UpstreamError):
        env.saga.initiate("u1", "S1", KEY)
    assert env.tuitions.rows["S1"]["status"] == "UNPAID"
    assert env.saga.repo.find_by_key(KEY).status == TxnStatus.FAILED.value


# ---------------- section 3: OTP ----------------
def test_wrong_otp_keeps_transaction_pending(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    with pytest.raises(BadRequest):
        env.saga.confirm("u1", txn.id, "000000")
    assert env.saga.repo.get(txn.id).status == TxnStatus.PENDING_OTP.value
    assert env.users.balances["u1"] == Decimal("20000000")


def test_expired_transaction_is_gone_and_tuition_released(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    env.saga.repo.update_fields(txn.id, expires_at=utcnow() - timedelta(seconds=1))
    with pytest.raises(Gone):
        env.saga.confirm("u1", txn.id, "123456")
    assert env.saga.repo.get(txn.id).status == TxnStatus.EXPIRED.value
    assert env.tuitions.rows["S1"]["status"] == "UNPAID"


def test_cancel_releases_the_tuition(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    assert env.saga.cancel("u1", txn.id).status == TxnStatus.CANCELLED.value
    assert env.saga.cancel("u1", txn.id).status == TxnStatus.CANCELLED.value  # twice is fine
    assert env.tuitions.rows["S1"]["status"] == "UNPAID"


# ---------------- section 4: compensation ----------------
def test_mark_paid_failure_refunds_and_releases(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    env.tuitions.commit_fails = True
    done = env.saga.confirm("u1", txn.id, "123456")
    assert done.status == TxnStatus.FAILED.value
    assert env.users.balances["u1"] == Decimal("20000000")  # money back
    assert env.tuitions.rows["S1"]["status"] == "UNPAID"


def test_refund_is_retried_by_the_job(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    env.tuitions.commit_fails, env.users.refund_supported = True, False
    done = env.saga.confirm("u1", txn.id, "123456")
    assert done.status == TxnStatus.FAILED.value and done.needs_refund
    env.users.refund_supported = True
    ExpiryJob(env.factory, lambda db: env.new_saga(), 1, 30).run_once()
    assert env.users.balances["u1"] == Decimal("20000000")
    assert not env.saga.repo.get(txn.id).needs_refund


def test_expiry_job_expires_pending(env):
    txn = env.saga.initiate("u1", "S1", KEY)
    env.saga.repo.update_fields(txn.id, expires_at=utcnow() - timedelta(seconds=1))
    assert ExpiryJob(env.factory, lambda db: env.new_saga(), 1, 30).run_once() == 1
    assert env.saga.repo.get(txn.id).status == TxnStatus.EXPIRED.value


# ---------------- section 5: concurrency ----------------
def test_concurrent_confirms_debit_once(env):
    """Same transaction confirmed 10 times at once -> one SUCCESS, money taken once.
    """
    txn = env.saga.initiate("u1", "S1", KEY)
    results = run_parallel(10, lambda i: env.new_saga().confirm("u1", txn.id, "123456"))
    assert sum(getattr(r, "status", None) == "SUCCESS" for r in results) == 1
    assert env.users.balances["u1"] == Decimal("5000000")
    assert len(env.users.debits) == 1


def test_same_account_cannot_overspend(env):
    """Case 1 of the assignment: two payments of one account at once, balance covers only one.
    """
    t1 = env.saga.initiate("u1", "S1", "key-account-1")  # 15M
    t2 = env.saga.initiate("u1", "S2", "key-account-2")  # 12M, balance 20M
    results = run_parallel(2, lambda i: env.new_saga().confirm("u1", (t1, t2)[i].id, "123456"))
    statuses = sorted(r.status for r in results)
    assert statuses == ["FAILED", "SUCCESS"]
    assert env.users.balances["u1"] >= 0
    spent = Decimal("20000000") - env.users.balances["u1"]
    assert spent in (Decimal("15000000"), Decimal("12000000"))
    failed = next(r for r in results if r.status == "FAILED")
    assert env.tuitions.rows["S1" if failed.id == t1.id else "S2"]["status"] == "UNPAID"  # released


def test_same_tuition_paid_once(env):
    """Case 2 of the assignment: two accounts pay the same MSSV at once -> exactly one can continue.
    """
    payers = ["u1", "u2"]
    results = run_parallel(2, lambda i: env.new_saga().initiate(payers[i], "S1", f"key-tuition-{i}"))
    winners = [r for r in results if getattr(r, "status", None) == "PENDING_OTP"]
    assert len(winners) == 1
    assert sum(isinstance(r, Conflict) for r in results) == 1
    winner = winners[0]
    assert env.saga.confirm(winner.payer_user_id, winner.id, "123456").status == "SUCCESS"
    assert env.tuitions.rows["S1"]["status"] == "PAID"
    assert len(env.users.debits) == 1
