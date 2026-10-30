"""HTTP layer: status codes, X-User-Id and Idempotency-Key handling (saga backed by the fakes)."""
import pytest
from fastapi.testclient import TestClient
from app.api.deps import get_saga
from app.main import app


@pytest.fixture
def client(env):
    app.dependency_overrides[get_saga] = env.new_saga
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def start(client, user="u1", mssv="S1", key="key-route-0001"):
    return client.post("/transactions", json={"student_id": mssv}, headers={"X-User-Id": user, "Idempotency-Key": key})


def test_missing_user_is_401(client):
    assert client.get("/transactions").status_code == 401


def test_initiate_verify_and_history(client):
    res = start(client)
    assert res.status_code == 201
    body = res.json()
    assert body["status"] == "PENDING_OTP" and 0 < body["otp_expires_in"] <= 300

    wrong = client.post(f"/transactions/{body['id']}/verify-otp", json={"otp": "000000"}, headers={"X-User-Id": "u1"})
    assert wrong.status_code == 400

    ok = client.post(f"/transactions/{body['id']}/verify-otp", json={"otp": "123456"}, headers={"X-User-Id": "u1"})
    assert ok.status_code == 200
    assert ok.json()["transaction"]["status"] == "SUCCESS" and ok.json()["balance_after"] == "5000000.00"

    again = client.post(f"/transactions/{body['id']}/verify-otp", json={"otp": "123456"}, headers={"X-User-Id": "u1"})
    assert again.status_code == 409
    assert [t["id"] for t in client.get("/transactions", headers={"X-User-Id": "u1"}).json()] == [body["id"]]


def test_other_users_transaction_is_404(client):
    txn_id = start(client).json()["id"]
    assert client.get(f"/transactions/{txn_id}", headers={"X-User-Id": "u2"}).status_code == 404


def test_error_codes(client):
    assert start(client, key="bad").status_code == 400
    assert start(client, user="poor").status_code == 422
    assert start(client, mssv="S3", key="key-route-0002").status_code == 409
    assert start(client, mssv="NOPE", key="key-route-0003").status_code == 404
    assert client.post("/transactions", json={"student_id": "S1"}, headers={"X-User-Id": "u1"}).status_code == 422
