"""PaymentSaga: the tuition payment workflow, sections 2 -> 4 of the assignment (orchestration saga).

Each step calls the service that owns the data; a step that fails undoes the earlier ones (compensation):

    initiate  : validate on server -> create PENDING_OTP -> reserve tuition -> issue OTP      (section 2 + 3)
    confirm   : verify OTP -> claim PENDING_OTP->PROCESSING -> complete()                     (section 3)
    complete  : re-check -> debit -> mark-paid -> SUCCESS + outbox event -> history          (section 4)
    _fail     : refund (if debited) -> release tuition -> FAILED                              (compensation)

complete() is idempotent (debit and mark-paid are idempotent per transaction_id), so the background job can
safely run it again for a transaction left in PROCESSING (e.g. a service timed out half way).
"""
import logging
from datetime import timedelta
from decimal import Decimal
from shared import events
from app.clients.base import UpstreamRejected, UpstreamUnavailable
from app.clients.otp_client import OtpCheck, OtpClient
from app.clients.tuition_client import PAID, RESERVED, Tuition, TuitionClient
from app.clients.user_client import Payer, UserClient
from app.core.errors import (BadRequest, Conflict, Gone, InsufficientBalance, NotFound, PaymentError,
                             TooManyRequests, UpstreamError)
from app.domain.models import Transaction, TxnStatus, utcnow
from app.repositories.transaction_repo import TransactionRepository

log = logging.getLogger("payment.saga")

KEY_MIN_LEN, KEY_MAX_LEN = 8, 64
PENDING, PROCESSING = TxnStatus.PENDING_OTP, TxnStatus.PROCESSING


class _Abort(Exception):
    """A re-check inside complete() failed -> compensate with this reason."""


class PaymentSaga:
    def __init__(self, repo: TransactionRepository, users: UserClient, tuitions: TuitionClient, otps: OtpClient,
                 otp_ttl_seconds: int = 300):
        self.repo, self.users, self.tuitions, self.otps = repo, users, tuitions, otps
        self.otp_ttl_seconds = otp_ttl_seconds

    # =====================================================================================================
    # Section 2: start a payment (POST /transactions)
    # =====================================================================================================
    def initiate(self, user_id: str, student_id: str, idempotency_key: str) -> Transaction:
        """Server-side checks (the UI is not trusted), then hold the tuition and email an OTP.
        """
        key = self._validate_key(idempotency_key)
        replay = self._replay(key, user_id)
        if replay:
            return replay  # same key sent again (double click / retry) -> same transaction

        payer = self._call(self.users.get_payer, user_id)  # payer = the logged-in account, never client data
        tuition = self._payable_tuition(student_id)  # amount always comes from tuition-service
        self._ensure_balance(payer.balance, tuition.amount)

        txn = self.repo.create(Transaction(payer_user_id=user_id, student_id=tuition.student_id,
                                           tuition_id=tuition.tuition_id, amount=tuition.amount,
                                           idempotency_key=key,
                                           expires_at=utcnow() + timedelta(seconds=self.otp_ttl_seconds)))
        if txn is None:  # a parallel request with the same key inserted first
            return self._replay(key, user_id)

        self._hold_tuition(txn)
        self._send_otp(txn, payer)
        log.info("txn %s PENDING_OTP: user=%s student=%s amount=%s", txn.id, user_id, txn.student_id, txn.amount)
        return self.repo.get(txn.id)

    # =====================================================================================================
    # Section 3: OTP (verify, resend) + cancel / expire
    # =====================================================================================================
    def confirm(self, user_id: str, txn_id: str, otp: str) -> Transaction:
        """Accept the OTP, then finish the payment. Only one concurrent confirm can win the claim.
        """
        txn = self._owned(user_id, txn_id)
        self._ensure_pending(txn)
        check = self._call(self.otps.verify, txn.id, otp)
        if not check.valid:
            raise BadRequest(_otp_message(check))
        if not self.repo.transition(txn.id, PENDING, PROCESSING):  # atomic claim
            raise Conflict("This transaction is already being confirmed")
        return self.complete(txn.id)

    def resend_otp(self, user_id: str, txn_id: str) -> int:
        """New OTP (the old one stops working) and the tuition hold is extended with it.
        """
        txn = self._owned(user_id, txn_id)
        self._ensure_pending(txn)
        payer = self._call(self.users.get_payer, user_id)
        expires_in = self._call(self.otps.issue, txn.id, payer.email, payer.full_name)
        try:
            self.tuitions.reserve(txn.tuition_id, txn.id)  # same transaction -> extends the hold
        except UpstreamRejected as e:
            self._fail(txn.id, f"Tuition hold lost: {e.detail}")
            raise Conflict("The tuition is no longer held for this transaction")
        except UpstreamUnavailable:
            pass  # the current hold still covers the new OTP window; the job cleans up later
        self.repo.update_fields(txn.id, expires_at=utcnow() + timedelta(seconds=expires_in))
        return expires_in

    def cancel(self, user_id: str, txn_id: str) -> Transaction:
        """User cancels while waiting for the OTP -> release the tuition. Cancelling twice is fine.
        """
        txn = self._owned(user_id, txn_id)
        if txn.status == TxnStatus.CANCELLED.value:
            return txn
        if not self.repo.transition(txn.id, PENDING, TxnStatus.CANCELLED, failure_reason="Cancelled by the user",
                                    completed_at=utcnow()):
            raise Conflict(f"Transaction is {self.repo.get(txn.id).status}, it cannot be cancelled")
        self._release(txn)
        self._record_history(txn.id)
        return self.repo.get(txn.id)

    def expire(self, txn: Transaction) -> bool:
        """OTP window is over -> EXPIRED and release the tuition at the same moment.
        """
        if not self.repo.transition(txn.id, PENDING, TxnStatus.EXPIRED,
                                    failure_reason="OTP was not confirmed in time", completed_at=utcnow()):
            return False
        self._release(txn)
        self._record_history(txn.id)
        return True

    # =====================================================================================================
    # Section 4: finish a confirmed payment
    # =====================================================================================================
    def complete(self, txn_id: str) -> Transaction:
        """Re-check -> debit -> mark-paid -> SUCCESS (+ email event) -> history -> final result.
        Idempotent: safe to call again for the same PROCESSING transaction.
        """
        txn = self.repo.get(txn_id)
        if txn is None or txn.status != PROCESSING.value:
            return txn
        try:
            payer = self.users.get_payer(txn.payer_user_id)
            if txn.debited:
                balance_after = txn.balance_after  # earlier run already debited (debit is once per txn)
            else:
                self._recheck_before_debit(txn, payer)  # 4.1 re-check transaction + balance
                balance_after = self.users.debit(txn.payer_user_id, txn.amount, txn.id)  # 4.2 debit
                self.repo.update_fields(txn.id, debited=True, balance_after=balance_after)
            self.tuitions.commit(txn.tuition_id, txn.id)  # 4.3 tuition -> PAID
        except _Abort as a:
            return self._fail(txn.id, str(a))
        except UpstreamRejected as e:
            return self._fail(txn.id, f"{e.service}: {e.detail}")
        except UpstreamUnavailable as e:
            log.warning("txn %s stays PROCESSING (%s); the expiry job will finish it", txn.id, e)
            return self.repo.get(txn.id)

        payload = {"email": payer.email, "full_name": payer.full_name, "transaction_id": txn.id,
                   "student_id": txn.student_id, "amount": str(txn.amount), "balance_after": str(balance_after)}
        if self.repo.mark_success(txn.id, balance_after, events.PAYMENT_COMPLETED, payload):  # 4.4 + 4.5 email event
            log.info("txn %s SUCCESS: balance_after=%s", txn.id, balance_after)
            self._record_history(txn.id)  # 4.4 user's history
        return self.repo.get(txn.id)  # 4.6 final result

    def retry_refund(self, txn: Transaction) -> bool:
        """Called by the job for FAILED transactions whose refund did not go through yet.
        """
        return self._refund(txn) if txn.debited and txn.needs_refund else False

    # ---------------- read ----------------
    def get(self, user_id: str, txn_id: str) -> Transaction:
        return self._owned(user_id, txn_id)

    def history(self, user_id: str) -> list[Transaction]:
        return self.repo.list_by_user(user_id)

    def current_balance(self, user_id: str) -> Decimal | None:
        try:
            return self.users.get_payer(user_id).balance
        except (UpstreamRejected, UpstreamUnavailable):
            return None

    # =====================================================================================================
    # Helpers: validation
    # =====================================================================================================
    @staticmethod
    def _validate_key(key: str | None) -> str:
        key = (key or "").strip()
        if not KEY_MIN_LEN <= len(key) <= KEY_MAX_LEN:
            raise BadRequest(f"Idempotency-Key must be {KEY_MIN_LEN}-{KEY_MAX_LEN} characters")
        return key

    def _replay(self, key: str, user_id: str) -> Transaction | None:
        existing = self.repo.find_by_key(key)
        if existing and existing.payer_user_id != user_id:
            raise Conflict("Idempotency-Key is already used by another request")
        return existing

    def _payable_tuition(self, student_id: str) -> Tuition:
        if not student_id or not student_id.strip():
            raise BadRequest("student_id is required")
        tuition = self._call(self.tuitions.lookup, student_id)
        if tuition.status == PAID:
            raise Conflict("This tuition is already paid")
        if tuition.status == RESERVED:
            raise Conflict("This tuition is being paid by another transaction")
        return tuition

    @staticmethod
    def _ensure_balance(balance: Decimal, amount: Decimal) -> None:
        if balance < amount:
            raise InsufficientBalance(f"Insufficient balance: {balance} < {amount}")

    def _owned(self, user_id: str, txn_id: str) -> Transaction:
        txn = self.repo.get_owned(txn_id, user_id)
        if txn is None:  # other users' transactions answer 404 too (ids cannot be probed)
            raise NotFound("Transaction not found")
        return txn

    def _ensure_pending(self, txn: Transaction) -> None:
        if txn.status == TxnStatus.EXPIRED.value:
            raise Gone("Transaction expired")
        if txn.status != PENDING.value:
            raise Conflict(f"Transaction is {txn.status}")
        if txn.expires_at and txn.expires_at <= utcnow():
            self.expire(txn)
            raise Gone("Transaction expired")

    def _recheck_before_debit(self, txn: Transaction, payer: Payer) -> None:
        self.tuitions.reserve(txn.tuition_id, txn.id)  # still ours? (409 -> UpstreamRejected -> compensate)
        if payer.balance < txn.amount:
            raise _Abort(f"Insufficient balance: {payer.balance} < {txn.amount}")

    # =====================================================================================================
    # Helpers: steps with compensation
    # =====================================================================================================
    def _hold_tuition(self, txn: Transaction) -> None:
        try:
            self.tuitions.reserve(txn.tuition_id, txn.id)
        except UpstreamRejected as e:
            self._fail(txn.id, f"Tuition hold refused: {e.detail}")
            raise _as_payment_error(e)
        except UpstreamUnavailable:
            self._fail(txn.id, "tuition-service unavailable")
            raise UpstreamError("Tuition service is unavailable, try again")

    def _send_otp(self, txn: Transaction, payer: Payer) -> None:
        try:
            expires_in = self.otps.issue(txn.id, payer.email, payer.full_name)  # OTP bound to txn_id
        except (UpstreamRejected, UpstreamUnavailable) as e:
            self._fail(txn.id, f"Could not send the OTP ({e})")
            raise UpstreamError("Could not send the OTP, try again")
        self.repo.update_fields(txn.id, expires_at=utcnow() + timedelta(seconds=expires_in))

    def _fail(self, txn_id: str, reason: str) -> Transaction:
        """Compensation: give the money back if it was taken, release the tuition, mark FAILED.
        """
        txn = self.repo.get(txn_id)
        if txn.debited:
            self._refund(txn)
        self._release(txn)
        if self.repo.transition(txn.id, (PENDING, PROCESSING), TxnStatus.FAILED, failure_reason=reason[:255],
                                completed_at=utcnow()):
            log.info("txn %s FAILED: %s", txn.id, reason)
            self._record_history(txn.id)
        return self.repo.get(txn.id)

    def _refund(self, txn: Transaction) -> bool:
        try:
            balance = self.users.refund(txn.payer_user_id, txn.amount, txn.id)
        except (UpstreamRejected, UpstreamUnavailable) as e:
            log.error("txn %s refund failed (%s); flagged for retry", txn.id, e)
            self.repo.update_fields(txn.id, needs_refund=True)
            return False
        self.repo.update_fields(txn.id, debited=False, needs_refund=False, balance_after=balance)
        log.info("txn %s refunded, balance=%s", txn.id, balance)
        return True

    def _release(self, txn: Transaction) -> None:
        try:
            self.tuitions.release(txn.tuition_id, txn.id)
        except (UpstreamRejected, UpstreamUnavailable) as e:
            log.warning("txn %s release failed (%s); the hold expires by itself", txn.id, e)

    def _record_history(self, txn_id: str) -> None:
        txn = self.repo.get(txn_id)
        try:
            self.users.record_history(txn.payer_user_id, txn.student_id, txn.tuition_id, txn.amount, txn.status,
                                      txn.failure_reason)
        except (UpstreamRejected, UpstreamUnavailable) as e:
            log.warning("txn %s history not recorded in user-service (%s)", txn.id, e)

    @staticmethod
    def _call(fn, *args):
        """Call a client for a step with nothing to undo; map its failure to an HTTP error.
        """
        try:
            return fn(*args)
        except UpstreamRejected as e:
            raise _as_payment_error(e)
        except UpstreamUnavailable as e:
            raise UpstreamError(str(e))


_STATUS_TO_ERROR = {404: NotFound, 409: Conflict, 422: InsufficientBalance, 429: TooManyRequests}


def _as_payment_error(e: UpstreamRejected) -> PaymentError:
    headers = {"Retry-After": e.headers["retry-after"]} if "retry-after" in e.headers else None
    return _STATUS_TO_ERROR.get(e.status_code, BadRequest)(e.detail, headers)


def _otp_message(check: OtpCheck) -> str:
    if check.reason == "invalid":
        return f"Wrong OTP, {check.attempts_left} attempt(s) left"
    if check.reason == "locked":
        return "Too many wrong OTPs, request a new one"
    return "OTP expired or already used, request a new one"
