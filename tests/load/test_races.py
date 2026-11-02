"""Deterministic concurrency checks (pytest), run in the `loadtest` container against the load-test stack:

    docker compose -f docker-compose.yml -f docker-compose.loadtest.yml --profile loadtest run --rm loadtest pytest -v

Each test resets the small "race" pool first (users lt-r1 = 30M, lt-r2 = 100M; students LTRACE01 = 15M,
LTRACE02 = 18.5M, LTRACE03 = 12M) and repeats ROUNDS times, because a race that is lost once can be won by luck.
OTPs come from the otp-service test hook (OTP_TEST_ECHO), not from email logs.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import httpx
import pytest
import lt_data as d

BASE = os.environ.get("BASE_URL", "http://web") + "/api"
OTP_URL = os.environ.get("OTP_SERVICE_URL", "http://otp-service:8000")
ROUNDS = int(os.environ.get("RACE_ROUNDS", "5"))
rounds = pytest.mark.parametrize("round_no", range(ROUNDS))


@pytest.fixture(autouse=True)
def fresh_race_pool():
    d.reset(d.RACE_USERS, list(d.RACE_STUDENTS))


def login(username: str) -> httpx.Client:
    c = httpx.Client(base_url=BASE, timeout=30)
    r = c.post("/auth/login", json={"username": username, "password": d.PASSWORD})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c


def balance(c: httpx.Client) -> Decimal:
    return Decimal(str(c.get("/accounts/me").json()["balance"]))


def initiate(c: httpx.Client, mssv: str, key: str | None = None) -> httpx.Response:
    return c.post("/transactions", json={"student_id": mssv}, headers={"Idempotency-Key": key or str(uuid.uuid4())})


def otp_for(txn_id: str) -> str:
    r = httpx.get(f"{OTP_URL}/internal/test/otp/{txn_id}")
    r.raise_for_status()
    return r.json()["otp"]


def parallel(fn, items):
    items = list(items)
    with ThreadPoolExecutor(len(items)) as ex:
        return list(ex.map(fn, items))


@rounds
def test_same_student_only_one_reservation_wins(round_no):
    payers = [login("lt-r1"), login("lt-r2")] * 4  # 8 attempts at once, 2 different accounts
    codes = parallel(lambda c: initiate(c, "LTRACE03").status_code, payers)
    assert sorted(codes) == [201] + [409] * 7


@rounds
def test_same_account_overdraft_is_impossible(round_no):
    """15M + 18.5M > 30M: both OTPs confirmed at the same moment -> exactly one is paid, balance stays >= 0."""
    r1 = login("lt-r1")
    t1, t2 = initiate(r1, "LTRACE01").json(), initiate(r1, "LTRACE02").json()
    pairs = [(t1["id"], otp_for(t1["id"])), (t2["id"], otp_for(t2["id"]))]
    res = parallel(lambda p: r1.post(f"/transactions/{p[0]}/verify-otp", json={"otp": p[1]}), pairs)
    assert [r.status_code for r in res] == [200, 200]
    txns = [r.json()["transaction"] for r in res]
    assert sorted(t["status"] for t in txns) == ["FAILED", "SUCCESS"]
    # "Insufficient balance: <balance> < <amount>" (re-check) or "user-service: Insufficient balance ..." (debit)
    assert "Insufficient balance" in next(t for t in txns if t["status"] == "FAILED")["failure_reason"]
    paid = next(Decimal(str(t["amount"])) for t in txns if t["status"] == "SUCCESS")
    assert balance(r1) == d.RACE_USERS["lt-r1"] - paid


@rounds
def test_same_idempotency_key_creates_one_transaction(round_no):
    r2, key = login("lt-r2"), str(uuid.uuid4())
    res = parallel(lambda _: initiate(r2, "LTRACE03", key), range(8))
    assert [r.status_code for r in res] == [201] * 8, [r.text for r in res]
    assert len({r.json()["id"] for r in res}) == 1


@rounds
def test_same_otp_submitted_twice_debits_once(round_no):
    r2 = login("lt-r2")
    txn = initiate(r2, "LTRACE03").json()
    otp = otp_for(txn["id"])
    res = parallel(lambda _: r2.post(f"/transactions/{txn['id']}/verify-otp", json={"otp": otp}), range(5))
    assert any(r.status_code == 200 and r.json()["transaction"]["status"] == "SUCCESS" for r in res)
    # the losers: 400 (code already used) or 409 "Transaction is PROCESSING" (the winner is still finishing)
    assert all(r.status_code in (200, 400, 409) for r in res), [r.text for r in res]
    assert balance(r2) == d.RACE_USERS["lt-r2"] - d.RACE_STUDENTS["LTRACE03"]


@rounds
def test_cancel_racing_verify_has_one_winner(round_no):
    """Cancel and the correct OTP at the same time: either the payment went through or it was cancelled, never both."""
    r2 = login("lt-r2")
    txn = initiate(r2, "LTRACE03").json()
    otp = otp_for(txn["id"])
    actions = [lambda: r2.post(f"/transactions/{txn['id']}/verify-otp", json={"otp": otp}),
               lambda: r2.post(f"/transactions/{txn['id']}/cancel")]
    parallel(lambda f: f(), actions)
    final = r2.get(f"/transactions/{txn['id']}").json()["status"]
    assert final in ("SUCCESS", "CANCELLED")
    expected = d.RACE_USERS["lt-r2"] - (d.RACE_STUDENTS["LTRACE03"] if final == "SUCCESS" else 0)
    assert balance(r2) == expected
    tuition = r2.get("/tuitions/LTRACE03").json()["status"]
    assert tuition == ("PAID" if final == "SUCCESS" else "UNPAID")
