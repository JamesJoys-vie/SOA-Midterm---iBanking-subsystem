"""Expiry / reconcile job. Each pass:
  1. PENDING_OTP past its OTP window -> EXPIRED + release the tuition (hold ends together with the OTP)
  2. PROCESSING for too long (a service timed out half way) -> run PaymentSaga.complete() again
  3. FAILED with needs_refund -> try the refund again
Safe with several replicas: every status change is a conditional UPDATE, debit / mark-paid are idempotent.
"""
from datetime import timedelta
from sqlalchemy.orm import sessionmaker
from app.domain.models import utcnow
from app.workers.periodic import PeriodicWorker


class ExpiryJob(PeriodicWorker):
    name = "expiry-job"

    def __init__(self, session_factory: sessionmaker, saga_factory, interval_s: float, stuck_after_s: int):
        super().__init__(interval_s)
        self.session_factory, self.saga_factory, self.stuck_after_s = session_factory, saga_factory, stuck_after_s

    def run_once(self) -> int:
        with self.session_factory() as db:
            saga = self.saga_factory(db)
            repo, now = saga.repo, utcnow()
            handled = sum(saga.expire(t) for t in repo.find_expired_pending(now))
            for txn in repo.find_stuck_processing(now - timedelta(seconds=self.stuck_after_s)):
                saga.complete(txn.id)
                handled += 1
            handled += sum(saga.retry_refund(t) for t in repo.find_pending_refunds())
        if handled:
            self.log.info("handled %d transaction(s)", handled)
        return handled
