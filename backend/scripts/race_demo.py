"""Race demo for section 5 (data consistency): fires requests at the SAME instant through the real gateway.

Scenarios
  same-account   (assignment case 1) one account confirms several payments at once -> never spends past its balance
  same-tuition   (assignment case 2) several accounts pay the same MSSV at once -> paid exactly once
  same-key       one request sent N times with the same Idempotency-Key -> one transaction
  double-confirm the correct OTP submitted N times at once -> one SUCCESS, money taken once

Run inside the compose network (it reads OTPs from the otp-service test endpoint, enabled by docker-compose.demo.yml):
    docker compose -f docker-compose.yml -f docker-compose.demo.yml --profile demo run --rm race-demo all
Every scenario uses up unpaid tuitions: re-seed the data (seed.py) before running it again.
"""
import argparse
import os
import sys
import threading
import uuid
from decimal import Decimal
import httpx

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8000")
OTP_SERVICE_URL = os.environ.get("OTP_SERVICE_URL", "http://otp-service:8000")
# "user:password,..." and "MSSV,..." of the seed data (override with env or CLI flags)
DEFAULT_USERS = os.environ.get("RACE_USERS", "alice:Password123!,bob:Password123!,carol:Password123!")
DEFAULT_MSSV = os.environ.get("RACE_MSSV", "52100001,522H0099,52100003,52100004")


class UserSession:
    """One logged-in user talking to the gateway."""

    def __init__(self, http: httpx.Client, username: str, password: str):
        self.http, self.username = http, username
        res = http.post("/api/auth/login", json={"username": username, "password": password})
        if res.status_code != 200:
            sys.exit(f"Login failed for {username}: {res.status_code} {res.text}")
        self.headers = {"Authorization": f"Bearer {res.json()['access_token']}"}

    def balance(self) -> Decimal:
        return Decimal(str(self.http.get("/api/accounts/me", headers=self.headers).json()["balance"]))

    def tuition(self, mssv: str) -> dict:
        return self.http.get(f"/api/tuitions/{mssv}", headers=self.headers).json()

    def initiate(self, mssv: str, key: str | None = None) -> httpx.Response:
        return self.http.post("/api/transactions", json={"student_id": mssv},
                              headers={**self.headers, "Idempotency-Key": key or str(uuid.uuid4())})

    def verify(self, txn_id: str, otp: str) -> httpx.Response:
        return self.http.post(f"/api/transactions/{txn_id}/verify-otp", json={"otp": otp}, headers=self.headers)

    def cancel(self, txn_id: str) -> httpx.Response:
        return self.http.post(f"/api/transactions/{txn_id}/cancel", headers=self.headers)


class RaceDemo:
    def __init__(self, users: list[tuple[str, str]], mssvs: list[str], parallel: int):
        self.http = httpx.Client(base_url=GATEWAY_URL, timeout=30, limits=httpx.Limits(max_connections=100))
        self.otp_http = httpx.Client(base_url=OTP_SERVICE_URL, timeout=10)
        self.sessions = [UserSession(self.http, u, p) for u, p in users]
        self.mssvs, self.parallel = mssvs, parallel

    # ---------------- scenarios ----------------
    def same_account(self, mssv_a: str, mssv_b: str) -> bool:
        user = self.sessions[0]
        _title(f"CASE 1 - one account ({user.username}) confirms 2 payments at the same instant")
        before = user.balance()
        amounts = [Decimal(str(user.tuition(m)["amount"])) for m in (mssv_a, mssv_b)]
        print(f"balance before = {before:,.0f}   tuitions = {[f'{a:,.0f}' for a in amounts]}")
        if sum(amounts) <= before:
            print("note: the balance covers both, so both may succeed. To show the protection, lower the balance in"
                  f" Adminer below {sum(amounts):,.0f} (but above each single amount) and run again.")
        txns = [self._start(user, m) for m in (mssv_a, mssv_b)]
        results = _fire(len(txns), lambda i: user.verify(txns[i], self._otp(txns[i])))
        statuses = [_txn_status(r) for r in results]
        after = user.balance()
        spent = sum(a for a, s in zip(amounts, statuses) if s == "SUCCESS")
        print(f"statuses = {statuses}   balance after = {after:,.0f}   spent = {spent:,.0f}")
        return _check(after >= 0 and after == before - spent, "balance never negative and = before - successful payments")

    def same_tuition(self, mssv: str) -> bool:
        _title(f"CASE 2 - {len(self.sessions)} accounts pay MSSV {mssv} at the same instant")
        results = _fire(len(self.sessions), lambda i: self.sessions[i].initiate(mssv))
        codes = [r.status_code for r in results]
        print(f"POST /transactions status codes = {codes}")
        winners = [(s, r.json()["id"]) for s, r in zip(self.sessions, results) if r.status_code == 201]
        ok = _check(len(winners) == 1, "exactly one account may continue (others get 409)")
        if winners:
            session, txn_id = winners[0]
            final = _txn_status(session.verify(txn_id, self._otp(txn_id)))
            tuition = session.tuition(mssv)
            print(f"winner {session.username}: {final}; tuition status now = {tuition['status']}")
            ok &= _check(final == "SUCCESS", "the single winner completes the payment")
        return ok

    def same_key(self, mssv: str) -> bool:
        user, key = self.sessions[0], str(uuid.uuid4())
        _title(f"EXTRA - the same Idempotency-Key sent {self.parallel} times at once")
        results = _fire(self.parallel, lambda i: user.initiate(mssv, key))
        ids = {r.json().get("id") for r in results if r.status_code == 201}
        print(f"status codes = {[r.status_code for r in results]}   distinct transaction ids = {len(ids)}")
        for txn_id in ids:
            user.cancel(txn_id)  # free the tuition for the next scenario
        return _check(len(ids) == 1, "one transaction for one key")

    def double_confirm(self, mssv: str) -> bool:
        user = self.sessions[0]
        _title(f"EXTRA - the correct OTP submitted {self.parallel} times at once")
        before, amount = user.balance(), Decimal(str(user.tuition(mssv)["amount"]))
        txn_id = self._start(user, mssv)
        otp = self._otp(txn_id)
        results = _fire(self.parallel, lambda i: user.verify(txn_id, otp))
        statuses = [_txn_status(r) for r in results]
        after = user.balance()
        print(f"results = {statuses}   balance {before:,.0f} -> {after:,.0f}")
        return _check(statuses.count("SUCCESS") == 1 and before - after == amount, "one SUCCESS, debited once")

    def run(self, scenario: str) -> bool:
        m = self.mssvs
        plan = {"same-account": lambda: self.same_account(m[0], m[1]),
                "same-tuition": lambda: self.same_tuition(m[2]),
                "same-key": lambda: self.same_key(m[3]),
                "double-confirm": lambda: self.double_confirm(m[3])}
        names = list(plan) if scenario == "all" else [scenario]
        return all([plan[n]() for n in names])

    # ---------------- helpers ----------------
    def _start(self, user: UserSession, mssv: str) -> str:
        res = user.initiate(mssv)
        if res.status_code != 201:
            sys.exit(f"Cannot start a payment for {mssv}: {res.status_code} {res.text} (re-seed the data?)")
        return res.json()["id"]

    def _otp(self, txn_id: str) -> str:
        """Latest OTP of a transaction (test endpoint, OTP_TEST_ECHO=true)."""
        res = self.otp_http.get(f"/internal/test/otp/{txn_id}")
        if res.status_code != 200:
            sys.exit("OTP test endpoint is off: start with -f docker-compose.demo.yml")
        return res.json()["otp"]


def _fire(n: int, fn) -> list:
    """Run fn(0..n-1) in n threads released together by a barrier (a real race)."""
    barrier, results = threading.Barrier(n), [None] * n

    def worker(i):
        barrier.wait()
        results[i] = fn(i)
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _txn_status(res: httpx.Response) -> str:
    return res.json()["transaction"]["status"] if res.status_code == 200 else f"HTTP {res.status_code}"


def _title(text: str) -> None:
    print("\n" + "=" * 100 + f"\n{text}\n" + "=" * 100)


def _check(ok: bool, rule: str) -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {rule}")
    return ok


def main() -> None:
    parser = argparse.ArgumentParser(description="Concurrency demo (section 5)")
    parser.add_argument("scenario", choices=["all", "same-account", "same-tuition", "same-key", "double-confirm"])
    parser.add_argument("--users", default=DEFAULT_USERS, help="user:password,user:password,...")
    parser.add_argument("--mssv", default=DEFAULT_MSSV, help="4 unpaid MSSV: A,B (case 1) C (case 2) D (extras)")
    parser.add_argument("--parallel", type=int, default=5)
    args = parser.parse_args()
    users = [tuple(u.split(":", 1)) for u in args.users.split(",")]
    mssvs = [m.strip() for m in args.mssv.split(",")]
    if len(users) < 2 or len(mssvs) < 4:
        sys.exit("Need at least 2 users and 4 unpaid MSSV")
    ok = RaceDemo(users, mssvs, args.parallel).run(args.scenario)
    print("\nALL CHECKS PASSED" if ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
