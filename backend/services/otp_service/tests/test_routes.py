"""The internal API as payment-service calls it, and the `otp.requested` event it publishes (no plain code in it).
Same real Redis (db 15, flushed) and run command as test_otp_store.py."""
import json
import pytest
import redis
from fastapi.testclient import TestClient
from pydantic import ValidationError
from shared import events
from shared.otp_crypto import OtpCipher
from app.core.config import Settings, settings
from app.main import app

BODY = {"transaction_id": "t1", "email": "a@example.com", "full_name": "Alice"}


@pytest.fixture
def r():
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not reachable")
    assert client.connection_pool.connection_kwargs.get("db") == 15, "tests flush the db: point REDIS_URL at db 15"
    client.flushdb()
    yield client
    client.flushdb()


@pytest.fixture
def api(r):
    return TestClient(app)


def published(r) -> list[tuple[dict, dict]]:
    """(raw stream fields, decoded payload) of every otp.requested entry."""
    return [(f, json.loads(f["payload"])) for _, f in r.xrange(events.stream_name(events.OTP_REQUESTED))]


def code_of(payload: dict) -> str:
    return OtpCipher(settings.otp_event_key).decrypt(payload["otp_enc"], payload["transaction_id"], 300)


def test_issue_publishes_encrypted_code_only(api, r):
    res = api.post("/internal/otp", json=BODY)
    assert res.status_code == 201 and res.json() == {"expires_in": settings.otp_ttl_seconds}
    (fields, payload), = published(r)
    assert "otp" not in payload
    assert payload | {"otp_enc": "x"} == {**BODY, "otp_enc": "x", "expires_in": settings.otp_ttl_seconds}
    code = code_of(payload)
    assert len(code) == 6 and code.isdigit()
    assert code not in json.dumps(fields)  # the plain code appears nowhere in the stored entry


def test_published_code_is_the_one_that_verifies(api, r):
    api.post("/internal/otp", json=BODY)
    (_, payload), = published(r)
    res = api.post("/internal/otp/verify", json={"transaction_id": "t1", "otp": code_of(payload)})
    assert res.json() == {"valid": True, "reason": None, "attempts_left": None}


def test_wrong_code_reports_attempts_left(api, r):
    api.post("/internal/otp", json=BODY)
    (_, payload), = published(r)
    wrong = f"{(int(code_of(payload)) + 1) % 1_000_000:06d}"
    res = api.post("/internal/otp/verify", json={"transaction_id": "t1", "otp": wrong})
    assert res.json() == {"valid": False, "reason": "invalid", "attempts_left": settings.otp_max_attempts - 1}


def test_unknown_transaction_is_expired(api):
    res = api.post("/internal/otp/verify", json={"transaction_id": "nope", "otp": "123456"})
    assert res.json()["valid"] is False and res.json()["reason"] == "expired"


def test_resend_too_soon_is_429_with_retry_after(api, r):
    assert api.post("/internal/otp", json=BODY).status_code == 201
    res = api.post("/internal/otp", json=BODY)
    assert res.status_code == 429
    assert 1 <= int(res.headers["Retry-After"]) <= settings.otp_resend_cooldown_seconds
    assert len(published(r)) == 1  # no second email


@pytest.mark.parametrize("key", ["", "not-a-key", "short"])
def test_invalid_key_stops_startup(key):
    with pytest.raises(ValidationError):
        Settings(redis_url="redis://x", otp_event_key=key)
