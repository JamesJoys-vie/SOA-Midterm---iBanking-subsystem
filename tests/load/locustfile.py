"""Locust load test for the tuition payment flow (runs in the `loadtest` container, see docker-compose.loadtest.yml).

    locust -f locustfile.py --headless -u 100 -r 10 -t 3m --csv /reports/<run>/stats

Virtual users (weights = share of the users spawned):
  PayerUser         (8)  normal customer: pays its OWN student over and over (lookup -> initiate -> OTP -> verify),
                         checks balance / history, and sometimes misbehaves (wrong OTP, cancel, abandon, double
                         submit, duplicate Idempotency-Key, resend too soon) on its spare "spoiler" student.
  HotStudentUser    (1)  many payers fight for the SAME 10 students -> exactly one reservation per term may win.
  SharedAccountUser (1)  several users share 5 small accounts and confirm payments at the same time -> the balance
                         must never go below 0; extra payments fail with "Insufficient balance" (422 or FAILED).

Expected business answers (409 lost race, 422 insufficient funds, 400 wrong OTP, 429 resend cooldown) are counted
as successes in the Locust stats and tallied in `outcomes.json`; anything else is a failure. Money correctness is
checked afterwards from the databases by verify_invariants.py.
"""
import itertools
import json
import os
import random
import threading
import uuid
from collections import Counter
import gevent
from gevent.pool import Group
import requests
from locust import HttpUser, between, events, task
from locust.exception import StopUser
import lt_data as d

OTP_URL = os.environ.get("OTP_SERVICE_URL", "http://otp-service:8000")
TERMINAL = {"SUCCESS", "FAILED", "CANCELLED", "EXPIRED"}
outcomes: Counter = Counter()
_otp_http = requests.Session()  # test hook, deliberately NOT recorded in the Locust stats
_lock = threading.Lock()


def tally(key: str) -> None:
    with _lock:
        outcomes[key] += 1


def fetch_otp(txn_id: str) -> str:
    """The OTP is issued before POST /transactions answers, so it is normally there on the first try."""
    for _ in range(20):
        r = _otp_http.get(f"{OTP_URL}/internal/test/otp/{txn_id}", timeout=5)
        if r.status_code == 200:
            return r.json()["otp"]
        gevent.sleep(0.1)
    raise RuntimeError(f"no OTP for {txn_id}")


@events.test_stop.add_listener
def _write_outcomes(environment, **_):
    print("Business outcomes:", json.dumps(dict(sorted(outcomes.items())), indent=2))
    if path := os.environ.get("OUTCOMES_FILE"):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(dict(sorted(outcomes.items())), f, indent=2)


class Base(HttpUser):
    abstract = True
    host = os.environ.get("BASE_URL", "http://web")
    username: str

    def on_start(self):
        with self.client.post("/api/auth/login", json={"username": self.username, "password": d.PASSWORD},
                              name="POST /auth/login", catch_response=True) as r:
            if r.status_code != 200:
                r.failure(f"login {self.username}: {r.status_code} {r.text[:120]}")
                raise StopUser()
        self.client.headers["Authorization"] = f"Bearer {r.json()['access_token']}"

    # helpers
    def call(self, method: str, path: str, name: str, expect=(200,), **kw):
        """Request that counts as a Locust success only if the status is one of `expect`."""
        with self.client.request(method, f"/api{path}", name=name, catch_response=True, **kw) as r:
            if r.status_code in expect:
                r.success()
            else:
                r.failure(f"{r.status_code} {r.text[:200]}")
        return r

    def lookup(self, mssv: str) -> dict | None:
        r = self.call("GET", f"/tuitions/{mssv}", "GET /tuitions/[mssv]")
        return r.json() if r.status_code == 200 else None

    def initiate(self, mssv: str, key: str | None = None, expect=(201,)):
        return self.call("POST", "/transactions", "POST /transactions", expect=expect,
                         json={"student_id": mssv}, headers={"Idempotency-Key": key or str(uuid.uuid4())})

    def verify(self, txn_id: str, otp: str, expect=(200,)):
        return self.call("POST", f"/transactions/{txn_id}/verify-otp", "POST /transactions/[id]/verify-otp",
                         expect=expect, json={"otp": otp})

    def wait_final(self, txn: dict) -> dict:
        """PROCESSING = money taken, tuition commit still finishing: poll like the frontend does."""
        for _ in range(30):
            if txn["status"] in TERMINAL:
                break
            gevent.sleep(1)
            txn = self.call("GET", f"/transactions/{txn['id']}", "GET /transactions/[id]").json()
        return txn

    def start_payment(self, mssv: str, pool: str, expect=(201,)) -> dict | None:
        """lookup + initiate. Returns the PENDING_OTP transaction, or None (tallied) if the payment cannot start."""
        info = self.lookup(mssv)
        if info is None:
            tally(f"{pool}: lookup failed")
            return None
        if info["status"] != "UNPAID":
            tally(f"{pool}: student {info['status'].lower()} at lookup")
            return None
        r = self.initiate(mssv, expect=expect)
        if r.status_code != 201:
            tally(f"{pool}: initiate {r.status_code}")
            return None
        return r.json()

    def finish(self, txn: dict, pool: str, expect=(200,)) -> dict | None:
        v = self.verify(txn["id"], fetch_otp(txn["id"]), expect=expect)
        if v.status_code != 200:
            tally(f"{pool}: verify {v.status_code}")
            return None
        final = self.wait_final(v.json()["transaction"])
        tally(f"{pool}: {final['status']}" + (f" ({final['failure_reason']})" if final["status"] == "FAILED" else ""))
        return final


class PayerUser(Base):
    weight = 8
    wait_time = between(0.5, 2)
    _ids = itertools.count()

    def on_start(self):
        self.n = next(PayerUser._ids) % d.N_NORMAL + 1  # > 300 users -> two virtual users share one customer
        self.username, self.mssv, self.spare = d.normal_user(self.n), d.normal_student(self.n), d.spoiler_student(self.n)
        super().on_start()

    @task(6)
    def pay_own_tuition(self):
        txn = self.start_payment(self.mssv, "normal")
        if txn:
            final = self.finish(txn, "normal")
            if final and final["status"] != "SUCCESS":
                tally("normal: UNEXPECTED non-success")

    @task(2)
    def view_history(self):
        self.call("GET", "/transactions", "GET /transactions")

    @task(2)
    def view_balance(self):
        self.call("GET", "/accounts/me", "GET /accounts/me")

    @task(1)
    def misbehave(self):
        random.choice([self.wrong_otp_first, self.cancel, self.abandon, self.double_submit,
                       self.duplicate_idempotency_key, self.resend_too_soon])()

    # ---- spoiler flows (spare student; 409 means an earlier abandoned payment still holds it -> fine)
    def wrong_otp_first(self):
        txn = self.start_payment(self.spare, "spoiler", expect=(201, 409))
        if not txn:
            return
        otp = fetch_otp(txn["id"])
        wrong = f"{(int(otp) + 1) % 1_000_000:06d}"
        r = self.verify(txn["id"], wrong, expect=(400,))
        tally(f"spoiler wrong-otp: {r.status_code}")
        self.finish(txn, "spoiler wrong-otp then right")

    def cancel(self):
        txn = self.start_payment(self.spare, "spoiler", expect=(201, 409))
        if txn:
            r = self.call("POST", f"/transactions/{txn['id']}/cancel", "POST /transactions/[id]/cancel")
            tally(f"spoiler cancel: {r.json().get('status') if r.status_code == 200 else r.status_code}")

    def abandon(self):
        if self.start_payment(self.spare, "spoiler", expect=(201, 409)):
            tally("spoiler abandon: left PENDING_OTP")  # the expiry job must turn it into EXPIRED

    def double_submit(self):
        """The same correct OTP sent 3x at once: one debit at most (ledger checked by verify_invariants.py)."""
        txn = self.start_payment(self.spare, "spoiler", expect=(201, 409))
        if not txn:
            return
        otp = fetch_otp(txn["id"])
        group = Group()
        # losers: 400 (code already used) or 409 "Transaction is PROCESSING" (the winner is still finishing)
        responses = group.map(lambda _: self.verify(txn["id"], otp, expect=(200, 400, 409)), range(3))
        ok = [r for r in responses if r.status_code == 200]
        tally(f"spoiler double-submit: {len(ok)}x200")
        if not ok:
            tally("spoiler double-submit: UNEXPECTED no 200")

    def duplicate_idempotency_key(self):
        """3 concurrent POST /transactions with one key must all return the same transaction."""
        info = self.lookup(self.spare)
        if not info or info["status"] != "UNPAID":
            return
        key = str(uuid.uuid4())
        responses = Group().map(lambda _: self.initiate(self.spare, key, expect=(201, 409)), range(3))
        codes = sorted(r.status_code for r in responses)
        ids = {r.json()["id"] for r in responses if r.status_code == 201}
        if len(ids) > 1:
            tally("spoiler idempotency: UNEXPECTED several transactions")
        elif codes == [201, 201, 201]:
            tally("spoiler idempotency: 3x same transaction")
        elif ids:  # one of OUR requests holds the tuition, so a 409 "being paid elsewhere" is wrong
            tally(f"spoiler idempotency: UNEXPECTED codes {codes}")
        else:  # an abandoned payment from an earlier flow still holds the spare student
            tally(f"spoiler idempotency: codes {codes}")
        if ids:
            self.finish({"id": ids.pop()}, "spoiler idempotency")

    def resend_too_soon(self):
        """Resend right after initiate -> 429 (30 s cooldown); the original OTP still works."""
        txn = self.start_payment(self.spare, "spoiler", expect=(201, 409))
        if not txn:
            return
        r = self.call("POST", f"/transactions/{txn['id']}/resend-otp", "POST /transactions/[id]/resend-otp",
                      expect=(429,))
        tally(f"spoiler resend-too-soon: {r.status_code}")
        self.finish(txn, "spoiler after resend")


class HotStudentUser(Base):
    weight = 1
    wait_time = between(0.1, 0.5)
    _ids = itertools.count()

    def on_start(self):
        self.username = d.hot_user(next(HotStudentUser._ids) % d.N_HOT_USERS + 1)
        super().on_start()

    @task
    def fight_for_student(self):
        mssv = d.hot_student(random.randint(1, d.N_HOT_STUDENTS))
        txn = self.start_payment(mssv, "hot", expect=(201, 409))  # 409 = someone else reserved it first
        if txn:
            self.finish(txn, "hot")


class SharedAccountUser(Base):
    weight = 1
    wait_time = between(0.2, 1)
    _ids = itertools.count()

    def on_start(self):
        self.username = d.shared_user(next(SharedAccountUser._ids) % d.N_SHARED_USERS + 1)
        super().on_start()

    def _pick(self) -> str:
        return d.shared_student(random.randint(1, d.N_SHARED_STUDENTS))

    @task(2)
    def pay(self):
        txn = self.start_payment(self._pick(), "shared", expect=(201, 409, 422))
        if txn:
            self.finish(txn, "shared")

    @task(1)
    def two_at_once(self):
        """Start two payments, then confirm both at the same moment (the account row lock decides)."""
        txns = [t for t in (self.start_payment(self._pick(), "shared", expect=(201, 409, 422)) for _ in range(2)) if t]
        Group().map(lambda t: self.finish(t, "shared burst"), txns)
