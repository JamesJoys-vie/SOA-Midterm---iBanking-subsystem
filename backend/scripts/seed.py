"""Seed demo data into the microservice databases (idempotent: skips existing records).

Usage:
  # Via Docker Compose:
  docker compose --profile tools run --rm seed

  # Or locally against SQLite / local MySQL:
  USERS_DB_URL="sqlite:///./user.db" TUITION_DB_URL="sqlite:///./tuition.db" python backend/scripts/seed.py
"""
import os
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# Ensure backend root is on sys.path so 'shared' can be imported when run directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine, text
from shared.security import hash_password

# Deterministic namespace for predictable IDs across seed runs
NS = uuid.UUID("11111111-1111-1111-1111-111111111111")
uid = lambda name: str(uuid.uuid5(NS, name))

USERS = [
    # username, password, full_name, phone, email, initial balance
    ("alice", "Password123!", "Nguyen Van A", "0900000001", "alice@example.com", Decimal("30000000")),
    ("bob",   "Password123!", "Tran Thi B",   "0900000002", "bob@example.com",   Decimal("5000000")),
    ("carol", "Password123!", "Le Van C",     "0900000003", "carol@example.com", Decimal("100000000")),
]

STUDENTS = [
    # student_id (MSSV), student_name, term, amount (one row per unpaid term)
    ("52100001", "Pham Minh D", "2025-HK1", Decimal("15000000")),
    ("52100002", "Hoang Thu E", "2025-HK1", Decimal("18500000")),
    ("52100003", "Vo Quoc F",   "2025-HK1", Decimal("12000000")),
    ("52100004", "Dang Mai G",  "2025-HK1", Decimal("40000000")),  # Exceeds Bob's balance -> insufficient balance demo
    # Concurrency and boundary test cases
    ("521H0081", "Nguyen Thanh Long", "2025-HK1", Decimal("16500000")),
    ("521E0001", "Tran Ngoc Anh",     "2025-HK1", Decimal("22000000")),
    ("E2400001", "Le Hoang Nam",      "2025-HK1", Decimal("9800000")),
    ("521H0102", "Pham Thu Trang",    "2025-HK1", Decimal("14200000")),
    ("522H0045", "Bui Duc Huy",       "2025-HK1", Decimal("17300000")),
    ("520K0123", "Do Minh Chau",      "2025-HK1", Decimal("11750000")),
    ("523C0007", "Ngo Gia Bao",       "2025-HK1", Decimal("4500000")),    # Bob (5M) can afford
    ("E2300112", "Vu Khanh Linh",     "2025-HK1", Decimal("3200000")),    # Bob (5M) can afford
    ("E2400050", "Dinh Cong Thanh",   "2025-HK1", Decimal("5000000")),    # Exactly Bob's balance (boundary condition)
    ("521V0042", "Huynh Tan Phat",    "2025-HK1", Decimal("13600000")),
    ("522H0099", "Kieu Anh Thu",      "2024-HK2", Decimal("9500000")),    # Oldest term: offered first
    ("522H0099", "Kieu Anh Thu",      "2025-HK1", Decimal("18000000")),   # Newer term: offered only after 2024-HK2 is paid
    ("52200011", "Ly Bao Ngoc",       "2025-HK1", Decimal("12500000")),
    ("52200012", "Mai Quoc Viet",     "2025-HK1", Decimal("19900000")),
    ("52200013", "Trinh Hai Yen",     "2025-HK1", Decimal("8750000")),
    ("52300021", "Duong Minh Khoa",   "2025-HK1", Decimal("21400000")),
    ("52300022", "Cao Thi Lan",       "2025-HK1", Decimal("10300000")),
    ("52300023", "Phan Van Tai",      "2025-HK1", Decimal("26800000")),
    ("52400031", "Ta Thu Ha",         "2025-HK1", Decimal("7600000")),
    ("52400032", "Lam Nhat Minh",     "2025-HK1", Decimal("15750000")),
    ("52400033", "Chau Ngoc Tram",    "2025-HK1", Decimal("120000000")),
]


def _ensure_tables_created(service_folder: str, engine) -> None:
    """Ensure database schema is created from SQLAlchemy models before seeding."""
    svc_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "services", service_folder))
    sys.path.insert(0, svc_dir)
    try:
        from app import models
        models.Base.metadata.create_all(bind=engine)
    finally:
        if svc_dir in sys.path:
            sys.path.remove(svc_dir)
        for mod_name in list(sys.modules.keys()):
            if mod_name == "app" or mod_name.startswith("app."):
                del sys.modules[mod_name]


def main() -> None:
    users_db_url = os.environ.get("USERS_DB_URL", "sqlite:///./user.db")
    tuition_db_url = os.environ.get("TUITION_DB_URL", "sqlite:///./tuition.db")

    users_engine = create_engine(users_db_url)
    tuition_engine = create_engine(tuition_db_url)

    # Automatically create tables if not existing
    _ensure_tables_created("user-service", users_engine)
    _ensure_tables_created("tuition-service", tuition_engine)

    now = datetime.now(timezone.utc)

    # 1. Seed users and accounts into user-service database
    with users_engine.begin() as conn:
        for username, password, full_name, phone, email, initial_balance in USERS:
            user_id = uid(username)
            # Insert user if not already existing
            existing_user = conn.execute(
                text("SELECT 1 FROM users WHERE username = :u"), {"u": username}
            ).first()
            if not existing_user:
                conn.execute(
                    text(
                        "INSERT INTO users (id, username, password_hash, full_name, phone, email, created_at) "
                        "VALUES (:id, :u, :h, :n, :p, :e, :cat)"
                    ),
                    {
                        "id": user_id,
                        "u": username,
                        "h": hash_password(password),
                        "n": full_name,
                        "p": phone,
                        "e": email,
                        "cat": now,
                    },
                )

            # Insert account if not already existing
            account_id = uid("acc-" + username)
            existing_account = conn.execute(
                text("SELECT 1 FROM accounts WHERE user_id = :u"), {"u": user_id}
            ).first()
            if not existing_account:
                conn.execute(
                    text(
                        "INSERT INTO accounts (id, user_id, balance, version) "
                        "VALUES (:id, :u, :b, 0)"
                    ),
                    {"id": account_id, "u": user_id, "b": str(initial_balance)},
                )

    # 2. Seed students and tuitions into tuition-service database
    with tuition_engine.begin() as conn:
        for mssv, name, term, amount in STUDENTS:
            # Insert student if not existing
            existing_student = conn.execute(
                text("SELECT 1 FROM students WHERE student_id = :s"), {"s": mssv}
            ).first()
            if not existing_student:
                conn.execute(
                    text("INSERT INTO students (student_id, full_name) VALUES (:s, :n)"),
                    {"s": mssv, "n": name},
                )

            # Insert tuition if not existing
            tuition_id = uid(f"tuition-{mssv}-{term}")
            existing_tuition = conn.execute(
                text("SELECT 1 FROM tuitions WHERE id = :id"), {"id": tuition_id}
            ).first()
            if not existing_tuition:
                conn.execute(
                    text(
                        "INSERT INTO tuitions (id, student_id, term, amount, status, version) "
                        "VALUES (:id, :s, :t, :a, 'UNPAID', 0)"
                    ),
                    {"id": tuition_id, "s": mssv, "t": term, "a": str(amount)},
                )

    distinct_students = len({s[0] for s in STUDENTS})
    print(f"Successfully seeded {distinct_students} students and {len(STUDENTS)} tuitions.")
    print("Demo accounts available: alice / bob / carol (Password: Password123!)")


if __name__ == "__main__":
    main()
