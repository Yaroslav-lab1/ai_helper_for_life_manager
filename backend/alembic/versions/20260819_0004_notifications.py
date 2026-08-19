"""Notification outbox for reminders and daily digests."""

from alembic import op
import sqlalchemy as sa


revision = "20260819_0004"
down_revision = "20260728_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(80), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(160), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_notification_deliveries_user_id", "notification_deliveries", ["user_id"])
    op.create_index("ix_notification_deliveries_kind", "notification_deliveries", ["kind"])
    op.create_index("ix_notification_deliveries_status", "notification_deliveries", ["status"])
    op.create_index("ix_notification_deliveries_scheduled_at", "notification_deliveries", ["scheduled_at"])
    op.create_index("ix_notification_deliveries_next_attempt_at", "notification_deliveries", ["next_attempt_at"])
    op.create_index(
        "ix_notification_deliveries_due",
        "notification_deliveries",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("notification_deliveries")
