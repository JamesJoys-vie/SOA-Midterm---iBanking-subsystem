"""Consumes `otp.requested` and `payment.completed` from Redis Streams (consumer group `notification`) and sends emails.
Handlers must be idempotent: a message can be delivered more than once (see shared/events.py)."""
import hashlib
import logging
import threading
from shared import events
from shared.otp_crypto import OtpCipher, OtpTokenError, OtpTokenExpired
from shared.redis_client import get_redis
from app.core.config import settings
from app.domain.mailer import is_permanent, send_email

log = logging.getLogger("notification.consumer")
GROUP = "notification"
DEDUPE_TTL_S = 86_400
# A failed send is retried after RECLAIM_IDLE_MS, at most MAX_DELIVERIES times, then dead-lettered (~1 min in all,
# well inside the 5 min OTP lifetime).
RECLAIM_IDLE_MS = 15_000
MAX_DELIVERIES = 5
# "sending" marker: blocks a second consumer while one sends. Outlives one SMTP attempt (15 s timeout) but expires
# long before the retries run out, so a consumer that died mid-send only delays the email.
SENDING_TTL_S = 30


def _vnd(amount) -> str:
    return f"{float(amount):,.0f} VND"


def _render(event_type: str, p: dict, code: str | None = None) -> tuple[str, str, str]:
    """-> (dedupe id, subject, body); `code` = the decrypted OTP for otp.requested"""
    if event_type == events.OTP_REQUESTED:
        # a resend reuses the transaction id with a new code (= new token); a redelivery carries the same token
        otp_id = hashlib.sha256(p["otp_enc"].encode()).hexdigest()[:16]
        return (f"{p['transaction_id']}:{otp_id}", "Your tuition payment OTP",
                f"Hello {p['full_name']},\n\n"
                f"Your one-time password is {code}.\n"
                f"It expires in {p['expires_in'] // 60} minutes and can be used once.\n"
                f"Transaction: {p['transaction_id']}\n\n"
                f"If you did not start this payment, ignore this email and do not share the code.")
    return (p["transaction_id"], "Tuition payment successful",
            f"Hello {p['full_name']},\n\n"
            f"Your payment of {_vnd(p['amount'])} for student {p['student_id']} was successful.\n"
            f"Remaining balance: {_vnd(p['balance_after'])}\n"
            f"Transaction: {p['transaction_id']}\n")


def _otp_code(cipher: OtpCipher, p: dict, msg_id: str) -> str | None:
    """The plain code of an otp.requested payload, or None when the code has expired (the email would only
    mislead the user). A token that does not decrypt is permanent: retries get the same answer."""
    if events.message_age_s(msg_id) >= p["expires_in"]:  # a late retry
        log.warning("OTP email for %s dropped: code expired before it could be sent", p["transaction_id"])
        return None
    try:
        return cipher.decrypt(p["otp_enc"], p["transaction_id"], p["expires_in"])
    except OtpTokenExpired:
        log.warning("OTP email for %s dropped: token older than the code lifetime", p["transaction_id"])
        return None
    except OtpTokenError as e:
        raise events.PermanentError(str(e)) from e


def make_handler(r, cipher: OtpCipher):
    def handle(event_type: str, payload: dict, msg_id: str) -> None:
        if event_type not in (events.OTP_REQUESTED, events.PAYMENT_COMPLETED):
            return
        if event_type == events.OTP_REQUESTED and "otp_enc" not in payload and "otp" in payload:
            # written before the code was encrypted: acked without a dead-letter copy, so the plain code is not
            # copied anywhere else (its code has long expired anyway)
            log.warning("old plain-text otp.requested %s dropped", msg_id)
            return
        try:
            code = None
            if event_type == events.OTP_REQUESTED:
                code = _otp_code(cipher, payload, msg_id)
                if code is None:
                    return
            dedupe_id, subject, body = _render(event_type, payload, code)
            to = payload["email"]
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            raise events.PermanentError(f"bad payload: {e!r}") from e
        sent_key = f"notif:sent:{event_type}:{dedupe_id}"
        sending_key = f"notif:sending:{event_type}:{dedupe_id}"
        if r.exists(sent_key):
            return  # already sent (redelivery)
        if not r.set(sending_key, 1, nx=True, ex=SENDING_TTL_S):
            raise events.RetryLater("another consumer is sending this email")
        try:
            if r.exists(sent_key):  # finished by another consumer between the two checks
                return
            send_email(to, subject, body)
            r.set(sent_key, 1, ex=DEDUPE_TTL_S)
        except Exception as e:
            if is_permanent(e):
                raise events.PermanentError(f"rejected by the mail server: {e}") from e
            raise
        finally:
            r.delete(sending_key)
    return handle


def _run(r, stop: threading.Event) -> None:
    """Keep the consumer alive across Redis hiccups (consume() raises on connection errors)."""
    handler = make_handler(r, OtpCipher(settings.otp_event_key))
    while not stop.is_set():
        try:
            events.consume(r, GROUP, [events.OTP_REQUESTED, events.PAYMENT_COMPLETED], handler,
                           reclaim_idle_ms=RECLAIM_IDLE_MS, max_deliveries=MAX_DELIVERIES, stop=stop)
        except Exception:
            log.exception("stream consumer crashed; restarting in 3s")
            stop.wait(3)


def start(redis_url: str, stop: threading.Event | None = None) -> threading.Thread:
    t = threading.Thread(target=_run, daemon=True, name="stream-consumer",
                         args=(get_redis(redis_url), stop or threading.Event()))
    t.start()
    return t
