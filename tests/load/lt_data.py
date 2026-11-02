"""Load-test data: seed + reset, kept apart from the demo data (every username starts with `lt-`, every MSSV with `LT`).

    python lt_data.py seed     create users / accounts / students / tuitions (idempotent, INSERT IGNORE)
    python lt_data.py reset    delete every load-test transaction and put balances + tuitions back to the seed state

Pools (each a separate concurrency situation):
  normal  lt-u001..lt-u300  own account (huge balance), own student LTN00001.. with TERMS_NORMAL unpaid terms
                            + a "spoiler" student LTX00001.. used for cancel / abandon / wrong-OTP flows
  hot     lt-h01..lt-h40    huge balances, all compete for the SAME 10 students LTHOT001..LTHOT010
  shared  lt-s1..lt-s5      several virtual users per account, balance runs out on purpose (overdraft attempts)
  race    lt-r1, lt-r2      small fixed data for tests/load/test_races.py (reset before every test)

A student with many terms works as a queue: tuition lookup offers the oldest unpaid term, so one MSSV can be paid
again and again during a run. Every user has the same password (one bcrypt hash, seeding stays fast).

Where the data lives (database per service): users, accounts, ledger_entries and the history table `transactions`
in users_db (user-service); students, tuitions in tuition_db; payment transactions + outbox in payments_db, linked
to the payer by payer_user_id only.
"""
import os
import sys
import uuid
from decimal import Decimal
import bcrypt
from sqlalchemy import bindparam, create_engine, text

PASSWORD = "LoadTest123!"
NS = uuid.UUID("22222222-2222-2222-2222-222222222222")  # differs from the demo seed namespace

N_NORMAL, TERMS_NORMAL, TERMS_SPOILER = 300, 60, 30
N_HOT_USERS, N_HOT_STUDENTS, TERMS_HOT = 40, 10, 100
N_SHARED_USERS, N_SHARED_STUDENTS, TERMS_SHARED = 5, 40, 50
HUGE = Decimal("100000000000")  # 100 billion: never the limiting factor (accounts.balance is NUMERIC(15, 2))
SHARED_BALANCE = Decimal("150000000")  # 150M vs 2-6M tuitions: runs out after ~35 payments

RACE_USERS = {"lt-r1": Decimal("30000000"), "lt-r2": Decimal("100000000")}
RACE_STUDENTS = {"LTRACE01": Decimal("15000000"), "LTRACE02": Decimal("18500000"), "LTRACE03": Decimal("12000000")}


def uid(name: str) -> str:
    return str(uuid.uuid5(NS, name))


def acc(username: str) -> str:
    return uid("acc-" + username)


def normal_user(i: int) -> str: return f"lt-u{i:03d}"
def normal_student(i: int) -> str: return f"LTN{i:05d}"
def spoiler_student(i: int) -> str: return f"LTX{i:05d}"
def hot_user(i: int) -> str: return f"lt-h{i:02d}"
def hot_student(i: int) -> str: return f"LTHOT{i:03d}"
def shared_user(i: int) -> str: return f"lt-s{i}"
def shared_student(i: int) -> str: return f"LTSHR{i:03d}"


def users() -> dict[str, Decimal]:
    """username -> starting balance."""
    out = {normal_user(i): HUGE for i in range(1, N_NORMAL + 1)}
    out |= {hot_user(i): HUGE for i in range(1, N_HOT_USERS + 1)}
    out |= {shared_user(i): SHARED_BALANCE for i in range(1, N_SHARED_USERS + 1)}
    return out | RACE_USERS


def _amount(seed: int, low_m: int, high_m: int) -> Decimal:
    """Deterministic amount between low and high million VND, in 100k steps."""
    steps = (high_m - low_m) * 10
    return Decimal(low_m * 1_000_000 + (seed * 7919 % (steps + 1)) * 100_000)


def tuitions() -> list[tuple[str, str, Decimal]]:
    """(mssv, term, amount) for every load-test tuition."""
    rows = []
    def add(mssv, n_terms, low, high, salt):
        rows.extend((mssv, f"T{t:03d}", _amount(salt * 1000 + t, low, high)) for t in range(1, n_terms + 1))
    for i in range(1, N_NORMAL + 1):
        add(normal_student(i), TERMS_NORMAL, 1, 3, i)
        add(spoiler_student(i), TERMS_SPOILER, 1, 3, 10_000 + i)
    for i in range(1, N_HOT_STUDENTS + 1):
        add(hot_student(i), TERMS_HOT, 1, 3, 20_000 + i)
    for i in range(1, N_SHARED_STUDENTS + 1):
        add(shared_student(i), TERMS_SHARED, 2, 6, 30_000 + i)
    rows.extend((mssv, "T001", amount) for mssv, amount in RACE_STUDENTS.items())
    return rows


def engines():
    return (create_engine(os.environ["USERS_DB_URL"]), create_engine(os.environ["TUITION_DB_URL"]),
            create_engine(os.environ["PAYMENTS_DB_URL"]))


def seed() -> None:
    users_db, tuition_db, _ = engines()
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt()).decode()
    all_users = users()
    with users_db.begin() as c:
        # user-service validates the email (EmailStr): reserved TLDs such as .invalid / .test are refused
        c.execute(text("INSERT IGNORE INTO users (id, username, password_hash, full_name, phone, email, created_at) "
                       "VALUES (:id, :u, :h, :n, '0999999999', :e, UTC_TIMESTAMP())"),
                  [{"id": uid(u), "u": u, "h": pw_hash, "n": f"Load Test {u}", "e": f"{u}@loadtest.example.com"}
                   for u in all_users])
        c.execute(text("INSERT IGNORE INTO accounts (id, user_id, balance, version) VALUES (:id, :u, :b, 0)"),
                  [{"id": acc(u), "u": uid(u), "b": b} for u, b in all_users.items()])
    rows = tuitions()
    with tuition_db.begin() as c:
        c.execute(text("INSERT IGNORE INTO students (student_id, full_name) VALUES (:s, :n)"),
                  [{"s": s, "n": f"Load Student {s}"} for s in sorted({r[0] for r in rows})])
        for start in range(0, len(rows), 5000):
            c.execute(text("INSERT IGNORE INTO tuitions (id, student_id, term, amount, status, version) "
                           "VALUES (:id, :s, :t, :a, 'UNPAID', 0)"),
                      [{"id": uid(f"tuition-{s}-{t}"), "s": s, "t": t, "a": a} for s, t, a in rows[start:start + 5000]])
    print(f"Load-test data: {len(all_users)} users, {len({r[0] for r in rows})} students, {len(rows)} tuitions "
          f"(password {PASSWORD})")


def reset(usernames: dict[str, Decimal] | None = None, students: list[str] | None = None) -> None:
    """Remove the transactions of the given users (default: all load-test users), restore their balances and
    put the given students' tuitions (default: every LT% student) back to UNPAID."""
    usernames = usernames if usernames is not None else users()
    users_db, tuition_db, pay_db = engines()
    expand = lambda sql: text(sql).bindparams(bindparam("ids", expanding=True))  # noqa: E731
    user_ids = {"ids": [uid(u) for u in usernames]}
    acc_ids = {"ids": [acc(u) for u in usernames]}
    with pay_db.begin() as c:
        txn_filter = "SELECT id FROM transactions WHERE payer_user_id IN :ids"
        c.execute(expand("DELETE FROM outbox_events WHERE JSON_UNQUOTE(JSON_EXTRACT(payload, '$.transaction_id')) "
                         f"IN ({txn_filter})"), user_ids)
        c.execute(expand("DELETE FROM transactions WHERE payer_user_id IN :ids"), user_ids)
    with users_db.begin() as c:
        c.execute(expand("DELETE FROM ledger_entries WHERE account_id IN :ids"), acc_ids)
        c.execute(expand("DELETE FROM transactions WHERE account_id IN :ids"), acc_ids)  # user-service history
        c.execute(text("UPDATE accounts SET balance = :b, version = 0 WHERE id = :id"),
                  [{"id": acc(u), "b": b} for u, b in usernames.items()])
    with tuition_db.begin() as c:
        sql = ("UPDATE tuitions SET status='UNPAID', reserved_by_txn=NULL, reserved_until=NULL, paid_by_txn=NULL, "
               "version=0 WHERE ")
        if students is None:
            c.execute(text(sql + "student_id LIKE 'LT%'"))
        else:
            c.execute(text(sql + "student_id IN :s").bindparams(bindparam("s", expanding=True)), {"s": students})


if __name__ == "__main__":
    if sys.argv[1:] == ["reset"]:
        reset()
        print("Load-test data reset (transactions removed, balances and tuitions restored)")
    else:
        seed()
