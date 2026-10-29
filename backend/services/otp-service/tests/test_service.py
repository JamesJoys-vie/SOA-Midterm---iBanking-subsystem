"""Unit tests for the OTP rules in app.service."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.models import Otp, OtpStatus
from app.notifier import OtpEmail
from app.service import OtpError, issue_otp, mask_email, send_otp, utcnow, verify_otp
from tests.conftest import FakeNotifier

def statuses(db, txn_id):
    """List the statuses of a transaction's OTPs, oldest first."""
    return [o.status for o in db.scalars(select(Otp).where(Otp.txn_id == txn_id).order_by(Otp.created_at))]

def test_issue_creates_six_digit_code_valid_for_five_minutes(db, settings):
    """A new OTP has a 6-digit code, lasts 300 s, and only its hash is stored."""
    now = utcnow()
    issued = issue_otp(db, "txn-1", settings, now=now)

    assert len(issued.code) == 6 and issued.code.isdigit()
    assert issued.otp.expires_at - now == timedelta(seconds=300)
    assert issued.otp.code_hash != issued.code  # plain code is not stored

def test_reissue_revokes_previous_otp_of_same_transaction(db, settings):
    """Issuing again (after the cooldown) revokes the old OTP, so its code stops working."""
    start = utcnow()
    first = issue_otp(db, "txn-1", settings, now=start)
    issue_otp(db, "txn-1", settings, now=start + timedelta(seconds=61))

    assert statuses(db, "txn-1") == ["REVOKED", "ACTIVE"]
    with pytest.raises(OtpError):
        verify_otp(db, "txn-1", first.code, settings)

def test_live_codes_are_unique_across_transactions(db, settings, monkeypatch):
    """A code clash with another transaction's live OTP is retried with a new code."""
    issue_otp(db, "txn-1", settings)
    taken = db.scalars(select(Otp)).one()
    codes = iter(["111111", "222222"])
    monkeypatch.setattr("app.service.generate_code", lambda _: next(codes))
    # Make "111111" the live code of txn-1, then ask txn-2 for an OTP: the first
    # attempt collides and must be retried with a different code.
    from app.service import hash_code
    taken.code_hash = hash_code("111111", settings.otp_secret)
    db.commit()

    issued = issue_otp(db, "txn-2", settings)

    assert issued.code == "222222"

def test_expired_code_can_be_reused_by_another_transaction(db, settings, monkeypatch):
    """Once expired, a code no longer blocks other transactions from getting it."""
    monkeypatch.setattr("app.service.generate_code", lambda _: "123456")
    start = utcnow()
    issue_otp(db, "txn-1", settings, now=start)

    issued = issue_otp(db, "txn-2", settings, now=start + timedelta(seconds=301))

    assert issued.code == "123456"
    assert statuses(db, "txn-1") == ["EXPIRED"]

def test_verify_success_marks_used(db, settings):
    """The right code marks the OTP USED and sets used_at."""
    issued = issue_otp(db, "txn-1", settings)

    otp = verify_otp(db, "txn-1", issued.code, settings)

    assert otp.status == OtpStatus.USED.value and otp.used_at is not None

def test_code_can_only_be_used_once(db, settings):
    """A second verify with the same code is refused."""
    issued = issue_otp(db, "txn-1", settings)
    verify_otp(db, "txn-1", issued.code, settings)

    with pytest.raises(OtpError) as err:
        verify_otp(db, "txn-1", issued.code, settings)
    assert err.value.code == "OTP_ALREADY_USED"

def test_code_is_bound_to_its_transaction(db, settings):
    """A code only works for the transaction it was issued for."""
    issued = issue_otp(db, "txn-1", settings)
    issue_otp(db, "txn-2", settings)

    with pytest.raises(OtpError) as err:
        verify_otp(db, "txn-2", issued.code, settings)
    assert err.value.code == "OTP_INVALID"

def test_expired_code_is_rejected(db, settings):
    """The right code is refused once expires_at is reached."""
    start = utcnow()
    issued = issue_otp(db, "txn-1", settings, now=start)

    with pytest.raises(OtpError) as err:
        verify_otp(db, "txn-1", issued.code, settings, now=start + timedelta(seconds=300))
    assert err.value.code == "OTP_EXPIRED"
    assert statuses(db, "txn-1") == ["EXPIRED"]

def test_wrong_attempts_are_counted_then_locked(db, settings):
    """Wrong codes count down attempts_left, then lock the OTP for good."""
    issued = issue_otp(db, "txn-1", settings)
    wrong = "000000" if issued.code != "000000" else "999999"

    left = []
    for _ in range(2):
        with pytest.raises(OtpError) as err:
            verify_otp(db, "txn-1", wrong, settings)
        assert err.value.code == "OTP_INVALID"
        left.append(err.value.attempts_left)
    with pytest.raises(OtpError) as err:
        verify_otp(db, "txn-1", wrong, settings)

    assert left == [2, 1]
    assert err.value.code == "OTP_LOCKED"
    # Even the right code is refused once locked.
    with pytest.raises(OtpError) as err:
        verify_otp(db, "txn-1", issued.code, settings)
    assert err.value.code == "OTP_LOCKED"

def test_unknown_transaction(db, settings):
    """Verifying a transaction with no OTP gives OTP_NOT_FOUND."""
    with pytest.raises(OtpError) as err:
        verify_otp(db, "nope", "123456", settings)
    assert err.value.code == "OTP_NOT_FOUND"
def email():
    """OtpEmail as built from payment-service's request (code filled in later)."""
    return OtpEmail(to="alice@example.com", payer_name="Nguyen Van A", mssv="52100001",
                    student_name="Pham Minh D", amount=15_000_000)

def test_resend_inside_cooldown_is_refused(db, settings):
    """A second code for the same transaction within 60 s is refused with the wait left."""
    start = utcnow()
    issue_otp(db, "txn-1", settings, now=start)

    with pytest.raises(OtpError) as err:
        issue_otp(db, "txn-1", settings, now=start + timedelta(seconds=18))
    assert err.value.code == "OTP_RESEND_TOO_SOON"
    assert err.value.retry_after == 42
    assert statuses(db, "txn-1") == ["ACTIVE"]  # the first code still works

def test_send_limit_per_transaction(db, settings):
    """After OTP_MAX_SENDS codes, no more are issued for that transaction."""
    start = utcnow()
    for i in range(settings.otp_max_sends):
        issue_otp(db, "txn-1", settings, now=start + timedelta(seconds=61 * i))

    with pytest.raises(OtpError) as err:
        issue_otp(db, "txn-1", settings, now=start + timedelta(seconds=61 * settings.otp_max_sends))
    assert err.value.code == "OTP_RESEND_LIMIT"

def test_send_otp_emails_the_code(db, settings):
    """send_otp fills in the code and expiry and hands the email to notification-service."""
    notifier = FakeNotifier()

    sent = send_otp(db, "txn-1", email(), settings, notifier)

    assert sent.sent_to == "a****@example.com"
    assert sent.sends_left == settings.otp_max_sends - 1
    [mail] = notifier.sent
    assert mail.expires_in == 300
    verify_otp(db, "txn-1", mail.code, settings)  # the emailed code is the real one

def test_failed_email_removes_the_otp(db, settings):
    """If the email can't be sent the new OTP is deleted and doesn't start a cooldown."""
    notifier = FakeNotifier()
    notifier.fail = True

    with pytest.raises(OtpError) as err:
        send_otp(db, "txn-1", email(), settings, notifier)
    assert err.value.code == "EMAIL_UNAVAILABLE"
    assert statuses(db, "txn-1") == []

    notifier.fail = False
    send_otp(db, "txn-1", email(), settings, notifier)  # retry right away is allowed
    assert len(notifier.sent) == 1

def test_mask_email():
    """Only the first letter of the local part stays visible."""
    assert mask_email("alice@example.com") == "a****@example.com"
