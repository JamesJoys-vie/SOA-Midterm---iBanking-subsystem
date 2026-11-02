"""Money-correctness checks after a load run, read straight from the service databases.

    python verify_invariants.py [--settle 150] [--out /reports/<run>/invariants.json]

Assumes the run started from `python lt_data.py reset`, so every load-test account began at its seed balance.
First waits (up to --settle seconds) until the system is quiet: no PROCESSING, no PENDING_OTP (abandoned
payments must be expired by the expiry job), no unpublished outbox event. Then checks:

  I1  no account balance below 0
  I2  per load-test account: balance == seed balance - sum(DEBIT) + sum(CREDIT)         (ledger explains every change)
  I3  ledger matches each transaction status (SUCCESS/PROCESSING: 1 DEBIT; FAILED: none or DEBIT+CREDIT refund;
      PENDING_OTP/CANCELLED/EXPIRED: none) and every ledger amount == transaction amount
  I4  every SUCCESS transaction <-> its tuition is PAID with paid_by_txn = that transaction, and vice versa
  I5  no tuition paid by more than one SUCCESS transaction
  I6  money out of load-test accounts == total of tuitions they marked PAID
  I7  every SUCCESS has exactly one published `payment.completed` outbox event
  I8  nothing stuck: no PROCESSING and no PENDING_OTP left once the settle window is over, no FAILED still
      waiting for its refund (needs_refund)
  W1  (warning) RESERVED tuition whose holder is no longer PENDING_OTP: release is best effort, the hold
      expires on its own (`reserved_until`), so this is reported but does not fail the run
  W2  (warning) user-service history rows per status != payment-service final transactions per status: the history
      call is best effort (payment-service only logs a failure), so this is reported but does not fail the run

Accounts, ledger and history are read from users_db (user-service), transactions and outbox from payments_db; a
transaction is tied to its account through payer_user_id (the account id is derived from the username in lt_data).
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import bindparam, text
import lt_data as d


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def quiet_state(pay) -> dict:
    with pay.connect() as c:
        return {
            "processing": c.execute(text("SELECT COUNT(*) FROM transactions WHERE status='PROCESSING'")).scalar(),
            # abandoned payments must be turned into EXPIRED by the expiry job (OTP window + job interval)
            "pending_otp": c.execute(text("SELECT COUNT(*) FROM transactions WHERE status='PENDING_OTP'")).scalar(),
            "unpublished_outbox": c.execute(text("SELECT COUNT(*) FROM outbox_events WHERE published=0")).scalar(),
            "refund_pending": c.execute(text("SELECT COUNT(*) FROM transactions WHERE needs_refund=1")).scalar(),
        }


def settle(pay, seconds: int) -> dict:
    """Wait for the expiry job / reconciler / outbox relay to finish their work."""
    deadline = time.time() + seconds
    while True:
        state = quiet_state(pay)
        if not any(state.values()) or time.time() > deadline:
            return state
        print(f"settling... {state}")
        time.sleep(5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--settle", type=int, default=150, help="max seconds to wait for background jobs")
    ap.add_argument("--out", help="write the result as JSON here")
    args = ap.parse_args()

    users_db, tuition_db, pay = d.engines()
    state = settle(pay, args.settle)
    seed_balance = {d.acc(u): b for u, b in d.users().items()}
    ids = list(seed_balance)
    account_of = {d.uid(u): d.acc(u) for u in d.users()}  # payer_user_id -> account id
    expand = lambda sql: text(sql).bindparams(bindparam("ids", expanding=True))  # noqa: E731

    with users_db.connect() as c:
        accounts = {r.id: r.balance for r in c.execute(text("SELECT id, balance FROM accounts"))}
        ledger = c.execute(expand("SELECT account_id, transaction_id, type, amount FROM ledger_entries "
                                  "WHERE account_id IN :ids"), {"ids": ids}).all()
        history = Counter(r.status for r in c.execute(expand(
            "SELECT status FROM transactions WHERE account_id IN :ids"), {"ids": ids}))
    with pay.connect() as c:
        txns = {r.id: r for r in c.execute(expand(
            "SELECT id, payer_user_id, tuition_id, amount, status, failure_reason FROM transactions "
            "WHERE payer_user_id IN :ids"), {"ids": list(account_of)})}
        outbox = Counter()
        for r in c.execute(text("SELECT JSON_UNQUOTE(JSON_EXTRACT(payload, '$.transaction_id')) AS txn, published "
                                "FROM outbox_events WHERE type='payment.completed'")):
            outbox[(r.txn, bool(r.published))] += 1
    with tuition_db.connect() as c:
        tuitions = {r.id: r for r in c.execute(text(
            "SELECT id, student_id, amount, status, reserved_by_txn, paid_by_txn FROM tuitions "
            "WHERE student_id LIKE 'LT%'"))}

    problems: dict[str, list[str]] = defaultdict(list)

    # I1
    for acc, bal in accounts.items():
        if bal < 0:
            problems["I1 negative balance"].append(f"{acc}: {bal}")

    # I2 + I3
    by_txn = defaultdict(list)
    debit, credit = Counter(), Counter()
    for e in ledger:
        by_txn[e.transaction_id].append(e)
        (debit if e.type == "DEBIT" else credit)[e.account_id] += e.amount
    for acc, start in seed_balance.items():
        if acc in accounts and accounts[acc] != start - debit[acc] + credit[acc]:
            problems["I2 balance not explained by ledger"].append(
                f"{acc}: seed {start} - debit {debit[acc]} + credit {credit[acc]} != {accounts[acc]}")
    allowed = {"SUCCESS": [("DEBIT",)], "PROCESSING": [("DEBIT",)], "FAILED": [(), ("CREDIT", "DEBIT")],
               "PENDING_OTP": [()], "CANCELLED": [()], "EXPIRED": [()]}
    for t in txns.values():
        kinds = tuple(sorted(e.type for e in by_txn[t.id]))
        if kinds not in allowed[t.status]:
            problems["I3 ledger does not match status"].append(f"{t.id} {t.status}: {kinds}")
        for e in by_txn[t.id]:
            if e.amount != t.amount:
                problems["I3 ledger amount != transaction amount"].append(f"{t.id}: {e.amount} vs {t.amount}")
        for e in by_txn[t.id]:
            if e.account_id != account_of[t.payer_user_id]:
                problems["I3 ledger entry on another account"].append(f"{t.id}: {e.account_id}")
    for txn_id in by_txn.keys() - txns.keys():
        problems["I3 ledger entry without transaction"].append(txn_id)

    # I4 + I5 + I6
    success = [t for t in txns.values() if t.status == "SUCCESS"]
    per_tuition = Counter(t.tuition_id for t in success)
    for tid, n in per_tuition.items():
        if n > 1:
            problems["I5 tuition paid more than once"].append(f"{tid}: {n} SUCCESS transactions")
    for t in success:
        tu = tuitions.get(t.tuition_id)
        if tu is None or tu.status != "PAID" or tu.paid_by_txn != t.id:
            problems["I4 SUCCESS without matching PAID tuition"].append(
                f"{t.id} -> {t.tuition_id}: {None if tu is None else (tu.status, tu.paid_by_txn)}")
    for tu in tuitions.values():
        if tu.status == "PAID":
            t = txns.get(tu.paid_by_txn)
            if t is None or t.status != "SUCCESS":
                problems["I4 PAID tuition without SUCCESS transaction"].append(
                    f"{tu.id} ({tu.student_id}) paid_by {tu.paid_by_txn}: {None if t is None else t.status}")
    net_out = sum(debit.values()) - sum(credit.values())
    paid_total = sum((tu.amount for tu in tuitions.values() if tu.status == "PAID"), Decimal(0))
    if net_out != paid_total:
        problems["I6 money out != tuition paid"].append(f"net debited {net_out} vs paid tuitions {paid_total}")

    # I7
    for t in success:
        if outbox[(t.id, True)] != 1 or outbox[(t.id, False)]:
            problems["I7 outbox event missing / duplicated / unpublished"].append(
                f"{t.id}: published {outbox[(t.id, True)]}, pending {outbox[(t.id, False)]}")

    # I8
    if state["processing"] or state["pending_otp"] or state["refund_pending"]:
        problems["I8 stuck transactions"].append(str(state))

    # W1
    stale_holds = [tu.id for tu in tuitions.values()
                   if tu.status == "RESERVED" and (tu.reserved_by_txn not in txns
                                                   or txns[tu.reserved_by_txn].status != "PENDING_OTP")]

    statuses = Counter(t.status for t in txns.values())
    # W2: PENDING_OTP / PROCESSING have no history row yet
    final = {k: v for k, v in statuses.items() if k in ("SUCCESS", "FAILED", "CANCELLED", "EXPIRED")}
    history_mismatch = {k: {"payments": final.get(k, 0), "history": history.get(k, 0)}
                        for k in final.keys() | history.keys() if final.get(k, 0) != history.get(k, 0)}
    failed_reasons = Counter(t.failure_reason for t in txns.values() if t.status == "FAILED")
    result = {
        "checked_at": utcnow().isoformat() + "Z",
        "transactions": dict(statuses),
        "failed_reasons": dict(failed_reasons),
        "ledger_entries": len(ledger),
        "net_debited": str(net_out),
        "tuition_paid_total": str(paid_total),
        "tuitions_paid": sum(tu.status == "PAID" for tu in tuitions.values()),
        "after_settle": state,
        "stale_holds_warning": len(stale_holds),
        "history_mismatch_warning": history_mismatch,
        "violations": {k: v[:20] + ([f"... {len(v) - 20} more"] if len(v) > 20 else []) for k, v in problems.items()},
        "passed": not problems,
    }
    print(json.dumps(result, indent=2, default=str))
    print("\nINVARIANTS", "PASSED" if not problems else f"FAILED ({sum(map(len, problems.values()))} violations)")
    if args.out:
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2, default=str)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
