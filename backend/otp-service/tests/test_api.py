"""HTTP tests for the otp-service endpoints."""
from app.config import settings

def test_issue_and_verify_over_http(client, monkeypatch):
    """Happy path through the HTTP endpoints; the code is not in the response."""
    monkeypatch.setattr("app.service.generate_code", lambda _: "482913")

    res = client.post("/otps", json={"txn_id": "txn-1"})
    assert res.status_code == 201
    body = res.json()
    assert body["otp_expires_in"] == settings.otp_ttl_seconds
    assert body["code"] is None  # never returned unless debug flag is on

    res = client.post("/otps/verify", json={"txn_id": "txn-1", "code": "482913"})
    assert res.status_code == 200
    assert res.json()["verified"] is True

def test_wrong_code_returns_400_with_attempts_left(client, monkeypatch):
    """A wrong code gives 400 with the error body the UI shows."""
    monkeypatch.setattr("app.service.generate_code", lambda _: "482913")
    client.post("/otps", json={"txn_id": "txn-1"})

    res = client.post("/otps/verify", json={"txn_id": "txn-1", "code": "111111"})

    assert res.status_code == 400
    assert res.json() == {
        "error": "OTP_INVALID",
        "message": "Incorrect code. 2 attempts left.",
        "attempts_left": 2,
    }

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
    assert anon_client.post("/otps", json={"txn_id": "txn-1"}).status_code == 401
    res = anon_client.post("/otps/verify", json={"txn_id": "txn-1", "code": "123456"},
                           headers={"X-Internal-Token": "wrong"})
    assert res.status_code == 401

def test_health_and_ready_need_no_token(anon_client):
    """Health checks stay open for Docker Compose."""
    assert anon_client.get("/health").json() == {"status": "ok"}
    assert anon_client.get("/ready").json() == {"status": "ready"}