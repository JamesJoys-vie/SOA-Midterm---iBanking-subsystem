"""Create transactions and outbox_events.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("payer_user_id", sa.String(36), nullable=False, index=True),
        sa.Column("student_id", sa.String(20), nullable=False),
        sa.Column("tuition_id", sa.String(36), nullable=False, index=True),
        sa.Column("amount", sa.Numeric(15, 2), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column("failure_reason", sa.String(255)),
        sa.Column("debited", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("needs_refund", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("balance_after", sa.Numeric(15, 2)),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.Column("expires_at", sa.DateTime, index=True),
        sa.Column("completed_at", sa.DateTime),
        sa.CheckConstraint("amount > 0", name="ck_transactions_amount_positive"),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("published", sa.Boolean, nullable=False, server_default=sa.false(), index=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("outbox_events")
    op.drop_table("transactions")
