"""The email handler: rendering, no duplicate email on redelivery, the "sending" marker, expired OTPs, error mapping."""
import smtplib
import time
import pytest
from shared import events
from app.workers import stream_consumer
from app.workers.stream_consumer import make_handler

OTP = {"email": "a@example.com", "full_name": "Alice", "otp": "123456", "transaction_id": "t1", "expires_in": 300}
PAID = {"email": "a@example.com", "full_name": "Alice", "transaction_id": "t1", "student_id": "52100001",
        "amount": "15000000.00", "balance_after": "15000000.00"}


def msg_id(age_s: float = 0) -> str:
    """A stream id as Redis would give it `age_s` seconds ago."""
    return f"{int((time.time() - age_s) * 1000)}-0"


@pytest.fixture
def sent(monkeypatch):
    """Replaces the SMTP call; each email lands in the list."""
    emails = []
    monkeypatch.setattr(stream_consumer, "send_email", lambda to, subject, body: emails.append((to, subject, body)))
    return emails


def test_otp_email_content(r, sent):
    make_handler(r)(events.OTP_REQUESTED, OTP, msg_id())
    to, subject, body = sent[0]
    assert to == "a@example.com" and subject == "Your tuition payment OTP"
    assert "123456" in body and "5 minutes" in body and "t1" in body


def test_receipt_email_content(r, sent):
    make_handler(r)(events.PAYMENT_COMPLETED, PAID, msg_id())
    _, subject, body = sent[0]
    assert subject == "Tuition payment successful"
    assert "15,000,000 VND" in body and "52100001" in body


def test_redelivery_sends_once(r, sent):
    handle = make_handler(r)
    handle(events.OTP_REQUESTED, OTP, msg_id())
    handle(events.OTP_REQUESTED, OTP, msg_id())
    assert len(sent) == 1
    assert not r.keys("notif:sending:*")  # marker released


def test_resend_with_new_code_is_a_new_email(r, sent):
    handle = make_handler(r)
    handle(events.OTP_REQUESTED, OTP, msg_id())
    handle(events.OTP_REQUESTED, {**OTP, "otp": "654321"}, msg_id())
    assert len(sent) == 2


def test_unknown_event_is_ignored(r, sent):
    make_handler(r)("something.else", {}, msg_id())
    assert sent == []


def test_failed_send_can_be_retried(r, monkeypatch, sent):
    calls = []

    def flaky(to, subject, body):
        calls.append(1)
        if len(calls) == 1:
            raise smtplib.SMTPServerDisconnected("gone")
        sent.append((to, subject, body))

    monkeypatch.setattr(stream_consumer, "send_email", flaky)
    handle = make_handler(r)
    with pytest.raises(smtplib.SMTPServerDisconnected):
        handle(events.OTP_REQUESTED, OTP, msg_id())
    assert not r.keys("notif:*")  # neither "sending" nor "sent" left behind
    handle(events.OTP_REQUESTED, OTP, msg_id())
    assert len(sent) == 1


def test_busy_marker_means_retry_later(r, sent):
    """Another consumer is sending (or died mid-send): retry later, and send once the marker is gone."""
    handle = make_handler(r)
    r.set("notif:sending:otp.requested:" + stream_consumer._render(events.OTP_REQUESTED, OTP)[0], 1, ex=30)
    with pytest.raises(events.RetryLater):
        handle(events.OTP_REQUESTED, OTP, msg_id())
    assert sent == []
    r.delete(*r.keys("notif:sending:*"))  # = the marker's 30 s expiring
    handle(events.OTP_REQUESTED, OTP, msg_id())
    assert len(sent) == 1


def test_marker_ttl_is_shorter_than_the_retry_window():
    retry_window_s = stream_consumer.RECLAIM_IDLE_MS / 1000 * (stream_consumer.MAX_DELIVERIES - 1)
    assert stream_consumer.SENDING_TTL_S < retry_window_s


def test_expired_otp_is_dropped(r, sent):
    make_handler(r)(events.OTP_REQUESTED, OTP, msg_id(age_s=301))
    assert sent == []


def test_old_receipt_is_still_sent(r, sent):
    make_handler(r)(events.PAYMENT_COMPLETED, PAID, msg_id(age_s=3600))
    assert len(sent) == 1


@pytest.mark.parametrize("payload", [{**OTP, "otp": None}, {k: v for k, v in OTP.items() if k != "email"},
                                     {**OTP, "expires_in": "300"}])
def test_bad_payload_is_permanent(r, sent, payload):
    with pytest.raises(events.PermanentError):
        make_handler(r)(events.OTP_REQUESTED, payload, msg_id())
    assert sent == []


def test_rejected_recipient_is_permanent(r, monkeypatch):
    def refuse(to, subject, body):
        raise smtplib.SMTPRecipientsRefused({to: (550, b"no such user")})

    monkeypatch.setattr(stream_consumer, "send_email", refuse)
    with pytest.raises(events.PermanentError):
        make_handler(r)(events.OTP_REQUESTED, OTP, msg_id())
    assert not r.keys("notif:*")


def test_temporary_rejection_is_retried(r, monkeypatch):
    def busy(to, subject, body):
        raise smtplib.SMTPRecipientsRefused({to: (451, b"try again later")})

    monkeypatch.setattr(stream_consumer, "send_email", busy)
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        make_handler(r)(events.OTP_REQUESTED, OTP, msg_id())
