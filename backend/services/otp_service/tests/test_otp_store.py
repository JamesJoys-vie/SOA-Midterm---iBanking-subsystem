"""OtpStore against a real Redis (the Lua scripts need one). Uses db 15 and flushes it.
Run inside the compose network (tests are not baked into the image, so mount them):
    docker compose run --rm --no-deps --entrypoint sh -e REDIS_URL=redis://redis:6379/15
        -v ./backend/services/otp_service/tests:/srv/service/tests otp-service
        -c "pip install -q pytest && python -m pytest -q tests"
"""
import os
import threading
import pytest
import redis
from app.repositories.otp_store import OtpStore, VerifyResult

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/15")


@pytest.fixture
def store():
    r = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        r.ping()
    except redis.ConnectionError:
        pytest.skip("Redis not reachable")
    assert r.connection_pool.connection_kwargs.get("db") == 15, "tests flush the db: point REDIS_URL at db 15"
    r.flushdb()
    yield OtpStore(r, ttl_seconds=300, max_attempts=3)
    r.flushdb()


def test_correct_code_is_single_use(store):
    assert store.save("t1", "123456")
    assert store.verify_and_consume("t1", "123456") is VerifyResult.OK
    assert store.verify_and_consume("t1", "123456") is VerifyResult.EXPIRED


def test_code_is_not_stored_in_plain_text(store):
    store.save("t1", "123456")
    assert "123456" not in str(store.r.hgetall("otp:txn:t1"))
    assert all("123456" not in k for k in store.r.keys("*"))


def test_ttl_is_set(store):
    store.save("t1", "123456")
    assert 0 < store.r.ttl("otp:txn:t1") <= 300


def test_active_codes_are_unique_across_transactions(store):
    assert store.save("t1", "111111")
    assert not store.save("t2", "111111")  # same code still active for t1
    store.verify_and_consume("t1", "111111")
    assert store.save("t2", "111111")  # free again once used


def test_resend_invalidates_previous_code(store):
    store.save("t1", "111111")
    store.save("t1", "222222")
    assert store.verify_and_consume("t1", "111111") is VerifyResult.INVALID
    assert store.verify_and_consume("t1", "222222") is VerifyResult.OK
    assert store.save("t9", "111111")  # old code's uniqueness key was dropped


def test_wrong_attempts_lock_the_otp(store):
    store.save("t1", "123456")
    assert store.verify_and_consume("t1", "000000") is VerifyResult.INVALID
    assert store.attempts_left("t1") == 2
    assert store.verify_and_consume("t1", "000001") is VerifyResult.INVALID
    assert store.verify_and_consume("t1", "000002") is VerifyResult.LOCKED
    assert store.verify_and_consume("t1", "123456") is VerifyResult.EXPIRED  # burned


def test_concurrent_verify_succeeds_once(store):
    store.save("t1", "123456")
    results, barrier = [], threading.Barrier(10)

    def go():
        barrier.wait()
        results.append(store.verify_and_consume("t1", "123456"))

    threads = [threading.Thread(target=go) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(VerifyResult.OK) == 1


def test_issue_rate_limit(store):
    assert store.acquire_issue_slot("t1", max_issues=2, cooldown_s=30, window_s=600) == 0
    assert store.acquire_issue_slot("t1", max_issues=2, cooldown_s=30, window_s=600) > 0  # cooldown
    store.r.delete("otp:cooldown:t1")
    assert store.acquire_issue_slot("t1", max_issues=2, cooldown_s=30, window_s=600) == 0
    store.r.delete("otp:cooldown:t1")
    assert store.acquire_issue_slot("t1", max_issues=2, cooldown_s=30, window_s=600) > 0  # max issues reached
