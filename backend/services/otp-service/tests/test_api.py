"""HTTP tests for the otp-service endpoints."""
from app.config import settings
from tests.conftest import OTP_REQUEST

def test_issue_and_verify_over_http(client, notifier, monkeypatch):
    """Happy path: the code is emailed, not returned, and then verifies."""
    monkeypatch.setattr("app.service.generate_code", lambda _: "482913")

    res = client.post("/otps", json=OTP_REQUEST)
    assert res.status_code == 201
    body = res.json()
    assert body["otp_expires_in"] == settings.otp_ttl_seconds
    assert body["sent_to"] == "a****@example.com"
    assert body["resend_available_in"] == settings.otp_resend_cooldown_seconds
    assert body["sends_left"] == settings.otp_max_sends - 1
    assert "code" not in body
    assert [(e.to, e.code, e.mssv) for e in notifier.sent] == [("alice@example.com", "482913", "52100001")]

    res = client.post("/otps/verify", json={"txn_id": "txn-1", "code": "482913"})
    assert res.status_code == 200
    assert res.json()["verified"] is True

def test_wrong_code_returns_400_with_attempts_left(client, monkeypatch):
    """A wrong code gives 400 with the error body the UI shows."""
    monkeypatch.setattr("app.service.generate_code", lambda _: "482913")
    client.post("/otps", json=OTP_REQUEST)

    res = client.post("/otps/verify", json={"txn_id": "txn-1", "code": "111111"})

    assert res.status_code == 400
    assert res.json() == {
        "error": "OTP_INVALID",
        "message": "Incorrect code. 2 attempts left.",
        "attempts_left": 2,
    }

def test_resend_too_soon_returns_429_with_retry_after(client):
    """Pressing resend inside the cooldown gives 429, a Retry-After header and the wait."""
    client.post("/otps", json=OTP_REQUEST)

    res = client.post("/otps", json=OTP_REQUEST)

    assert res.status_code == 429
    assert res.json()["error"] == "OTP_RESEND_TOO_SOON"
    assert 0 < res.json()["retry_after"] <= settings.otp_resend_cooldown_seconds
    assert res.headers["Retry-After"] == str(res.json()["retry_after"])

def test_email_failure_returns_503(client, notifier):
    """If notification-service is down, the request fails with 503 EMAIL_UNAVAILABLE."""
    notifier.fail = True

    res = client.post("/otps", json=OTP_REQUEST)

    assert res.status_code == 503
    assert res.json()["error"] == "EMAIL_UNAVAILABLE"

def test_invalid_email_is_rejected(client):
    """A malformed payer email fails request validation (422)."""
    res = client.post("/otps", json={**OTP_REQUEST, "email": "not-an-email"})
    assert res.status_code == 422

def test_unknown_transaction_returns_404(client):
    """Verifying an unknown transaction gives 404."""
    res = client.post("/otps/verify", json={"txn_id": "nope", "code": "123456"})
    assert res.status_code == 404
    assert res.json()["error"] == "OTP_NOT_FOUND"

def test_non_numeric_code_is_rejected(client):
    """Codes with non-digits fail request validation (422)."""
    res = client.post("/otps/verify", json={"txn_id": "txn-1", "code": "12ab56"})
    assert res.status_code == 422

def test_otp_endpoints_require_internal_token(anon_client):
    """Missing or wrong X-Internal-Token gives 401."""
    assert anon_client.post("/otps", json=OTP_REQUEST).status_code == 401
    res = anon_client.post("/otps/verify", json={"txn_id": "txn-1", "code": "123456"},
                           headers={"X-Internal-Token": "wrong"})
    assert res.status_code == 401

def test_health_and_ready_need_no_token(anon_client):
    """Health checks stay open for Docker Compose."""
    assert anon_client.get("/health").json() == {"status": "ok"}
    assert anon_client.get("/ready").json() == {"status": "ready"}
