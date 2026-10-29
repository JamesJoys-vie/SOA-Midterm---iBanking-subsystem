"""HTTP tests for the notification-service endpoints."""
from tests.conftest import OTP_EMAIL, RECEIPT_EMAIL

def test_otp_email_contains_code_and_payment(client, mailer):
    """The OTP email carries the code, expiry and what is being paid, in text and HTML."""
    res = client.post("/emails/otp", json=OTP_EMAIL)

    assert res.status_code == 200 and res.json() == {"status": "sent"}
    [(to, subject, text, html)] = mailer.sent
    assert to == "alice@example.com"
    assert "482913" not in subject  # kept out of lock-screen previews
    for body in (text, html):
        assert "482913" in body
        assert "5 minutes" in body
        assert "52100001" in body and "Pham Minh D" in body
        assert "15,000,000 ₫" in body

def test_otp_email_can_be_sent_again(client, mailer):
    """OTP emails are not deduplicated: a resend is a new email."""
    client.post("/emails/otp", json=OTP_EMAIL)
    client.post("/emails/otp", json={**OTP_EMAIL, "code": "551200"})
    assert len(mailer.sent) == 2

def test_receipt_email_contains_payment_details(client, mailer):
    """The receipt shows transaction, student, term, amounts and time in Vietnam time."""
    res = client.post("/emails/receipt", json=RECEIPT_EMAIL)

    assert res.status_code == 200 and res.json() == {"status": "sent"}
    [(_, subject, text, html)] = mailer.sent
    assert "successful" in subject
    for body in (text, html):
        assert "7f3a-c21e" in body and "2025-HK1" in body
        assert "15,000,000 ₫" in body
        assert "09/10/2026 14:32 (UTC+7)" in body  # 07:32 UTC

def test_receipt_is_sent_once_per_transaction(client, mailer):
    """A retry for the same txn_id answers already_sent and sends nothing."""
    client.post("/emails/receipt", json=RECEIPT_EMAIL)

    res = client.post("/emails/receipt", json=RECEIPT_EMAIL)

    assert res.json() == {"status": "already_sent"}
    assert len(mailer.sent) == 1

def test_failed_receipt_can_be_retried(client, mailer):
    """If the mail server is down: 503, and a later retry does send the receipt."""
    mailer.fail = True
    res = client.post("/emails/receipt", json=RECEIPT_EMAIL)
    assert res.status_code == 503
    assert res.json()["error"] == "EMAIL_UNAVAILABLE"

    mailer.fail = False
    res = client.post("/emails/receipt", json=RECEIPT_EMAIL)
    assert res.json() == {"status": "sent"}
    assert len(mailer.sent) == 1

def test_html_escapes_user_data(client, mailer):
    """Names are escaped in the HTML email, so they can't inject markup."""
    client.post("/emails/otp", json={**OTP_EMAIL, "payer_name": "<script>x</script>"})
    html = mailer.sent[0][3]
    assert "<script>" not in html and "&lt;script&gt;" in html

def test_invalid_requests_are_rejected(client):
    """Bad email address or non-numeric code fail validation (422)."""
    assert client.post("/emails/otp", json={**OTP_EMAIL, "to": "nope"}).status_code == 422
    assert client.post("/emails/otp", json={**OTP_EMAIL, "code": "12ab"}).status_code == 422

def test_email_endpoints_require_internal_token(anon_client):
    """Missing or wrong X-Internal-Token gives 401."""
    assert anon_client.post("/emails/otp", json=OTP_EMAIL).status_code == 401
    res = anon_client.post("/emails/receipt", json=RECEIPT_EMAIL, headers={"X-Internal-Token": "wrong"})
    assert res.status_code == 401

def test_health_and_ready_need_no_token(anon_client):
    """Health checks stay open for Docker Compose."""
    assert anon_client.get("/health").json() == {"status": "ok"}
    assert anon_client.get("/ready").json() == {"status": "ready"}
