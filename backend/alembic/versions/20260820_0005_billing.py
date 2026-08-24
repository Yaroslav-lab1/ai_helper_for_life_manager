"""YooKassa subscriptions, payments and webhook idempotency.

Revision ID: 20260820_0005
Revises: 20260819_0004
"""

from alembic import op
import sqlalchemy as sa


revision = "20260820_0005"
down_revision = "20260819_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("plan_code", sa.String(24), nullable=False, server_default="free"),
        sa.Column("billing_interval", sa.String(16), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="free"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("scheduled_plan_code", sa.String(24), nullable=True),
        sa.Column("scheduled_billing_interval", sa.String(16), nullable=True),
        sa.Column("yookassa_payment_method_id", sa.String(64), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_user_subscriptions_user_id"),
        sa.CheckConstraint("plan_code IN ('free','pro','executive')", name="ck_user_subscriptions_plan"),
        sa.CheckConstraint(
            "status IN ('free','pending','active','past_due','cancel_scheduled','canceled','expired')",
            name="ck_user_subscriptions_status",
        ),
        sa.CheckConstraint(
            "billing_interval IS NULL OR billing_interval IN ('monthly','yearly')",
            name="ck_user_subscriptions_interval",
        ),
    )
    op.create_index("ix_user_subscriptions_due", "user_subscriptions", ["status", "current_period_end"])
    op.create_index("ix_user_subscriptions_retry", "user_subscriptions", ["status", "next_retry_at"])

    # One FREE row per existing user. The statement is supported by SQLite and PostgreSQL.
    op.execute(
        sa.text(
            "INSERT INTO user_subscriptions "
            "(user_id, plan_code, status, cancel_at_period_end, retry_count, created_at, updated_at) "
            "SELECT id, 'free', 'free', false, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM users"
        )
    )

    op.create_table(
        "billing_payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(24), nullable=False, server_default="yookassa"),
        sa.Column("provider_payment_id", sa.String(64), nullable=True),
        sa.Column("idempotence_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("plan_code", sa.String(24), nullable=False),
        sa.Column("plan_name", sa.String(80), nullable=False),
        sa.Column("billing_interval", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="created"),
        sa.Column("description", sa.String(128), nullable=False),
        sa.Column("confirmation_url", sa.Text(), nullable=True),
        sa.Column("payment_method_saved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subscription_id"], ["user_subscriptions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("provider_payment_id", name="uq_billing_payments_provider_payment_id"),
        sa.UniqueConstraint("idempotence_key", name="uq_billing_payments_idempotence_key"),
        sa.UniqueConstraint(
            "subscription_id", "kind", "period_start", name="uq_billing_payments_renewal_period"
        ),
        sa.CheckConstraint("kind IN ('initial','renewal')", name="ck_billing_payments_kind"),
        sa.CheckConstraint("plan_code IN ('pro','executive')", name="ck_billing_payments_plan"),
        sa.CheckConstraint("billing_interval IN ('monthly','yearly')", name="ck_billing_payments_interval"),
        sa.CheckConstraint(
            "status IN ('created','pending','waiting_for_capture','processing','retry','succeeded','canceled','refunded')",
            name="ck_billing_payments_status",
        ),
        sa.CheckConstraint("amount >= 0", name="ck_billing_payments_amount"),
    )
    op.create_index("ix_billing_payments_user_created", "billing_payments", ["user_id", "created_at"])
    op.create_index("ix_billing_payments_status", "billing_payments", ["status"])

    op.create_table(
        "billing_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provider", sa.String(24), nullable=False, server_default="yookassa"),
        sa.Column("event_key", sa.String(180), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("provider_object_id", sa.String(64), nullable=False),
        sa.Column("processing_status", sa.String(24), nullable=False, server_default="received"),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_class", sa.String(120), nullable=True),
        sa.UniqueConstraint("event_key", name="uq_billing_webhook_events_event_key"),
        sa.CheckConstraint(
            "processing_status IN ('received','processing','processed','failed')",
            name="ck_billing_webhook_events_status",
        ),
    )
    op.create_index("ix_billing_webhook_events_received", "billing_webhook_events", ["received_at"])


def downgrade() -> None:
    op.drop_table("billing_webhook_events")
    op.drop_table("billing_payments")
    op.drop_table("user_subscriptions")
