"""Production readiness: UTC timestamps, revocable auth and privacy consent."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from alembic import op
import sqlalchemy as sa


revision = "20260728_0003"
down_revision = "20260719_0002"
branch_labels = None
depends_on = None


TIMESTAMP_COLUMNS = {
    "users": ["created_at"],
    "events": ["start_at", "end_at", "created_at"],
    "tasks": ["due_at", "reminder_at", "completed_at", "created_at"],
    "goals": ["created_at"],
    "habits": ["created_at"],
    "recommendations": ["created_at"],
    "chat_messages": ["created_at"],
    "ai_conversations": ["created_at", "updated_at"],
    "ai_messages": ["created_at"],
    "goal_plans": ["created_at", "updated_at"],
    "goal_plan_versions": ["created_at"],
    "ai_action_proposals": ["created_at", "updated_at"],
}


def _convert_sqlite_user_local_values() -> None:
    connection = op.get_bind()
    for table, columns in {"events": ["start_at", "end_at"], "tasks": ["due_at", "reminder_at"]}.items():
        rows = connection.execute(
            sa.text(
                f"SELECT item.id, users.timezone, {', '.join(f'item.{column}' for column in columns)} "
                f"FROM {table} AS item JOIN users ON users.id = item.user_id"
            )
        ).all()
        for row in rows:
            values: dict[str, object] = {"row_id": row[0]}
            try:
                zone = ZoneInfo(row[1] or "UTC")
            except ZoneInfoNotFoundError:
                zone = ZoneInfo("UTC")
            assignments: list[str] = []
            for index, column in enumerate(columns, start=2):
                raw = row[index]
                if raw is None:
                    continue
                value = raw if isinstance(raw, datetime) else datetime.fromisoformat(str(raw))
                if value.tzinfo is None:
                    value = value.replace(tzinfo=zone)
                values[column] = value.astimezone(UTC).replace(tzinfo=None).isoformat(sep=" ")
                assignments.append(f"{column} = :{column}")
            if assignments:
                connection.execute(
                    sa.text(f"UPDATE {table} SET {', '.join(assignments)} WHERE id = :row_id"),
                    values,
                )


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("SET TIME ZONE 'UTC'")
        for table, columns in {"events": ["start_at", "end_at"], "tasks": ["due_at", "reminder_at"]}.items():
            for column in columns:
                op.execute(
                    f"UPDATE {table} AS item SET {column} = "
                    f"(item.{column} AT TIME ZONE users.timezone) AT TIME ZONE 'UTC' "
                    f"FROM users WHERE users.id = item.user_id AND item.{column} IS NOT NULL"
                )
    elif dialect == "sqlite":
        _convert_sqlite_user_local_values()

    if dialect == "postgresql":
        for table, columns in TIMESTAMP_COLUMNS.items():
            for column in columns:
                op.alter_column(
                    table,
                    column,
                    existing_type=sa.DateTime(),
                    type_=sa.DateTime(timezone=True),
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'",
                )

    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("sessions_revoked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_settings", sa.Column("ai_context_consent_version", sa.String(30), nullable=True))
    op.add_column("user_settings", sa.Column("ai_context_consent_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("user_settings", sa.Column("ai_context_consent_revoked_at", sa.DateTime(timezone=True), nullable=True))

    for table in ("events", "tasks", "goals", "habits", "balance_assessments", "recommendations", "chat_messages"):
        op.add_column(table, sa.Column("demo_seed_key", sa.String(80), nullable=True))
        op.create_index(f"ix_{table}_demo_seed_key", table, ["demo_seed_key"])

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["auth_sessions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_family_id", "auth_sessions", ["family_id"])
    op.create_index("ix_auth_sessions_token_hash", "auth_sessions", ["token_hash"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    op.create_table(
        "one_time_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("purpose", sa.String(40), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_one_time_tokens_user_id", "one_time_tokens", ["user_id"])
    op.create_index("ix_one_time_tokens_purpose", "one_time_tokens", ["purpose"])
    op.create_index("ix_one_time_tokens_token_hash", "one_time_tokens", ["token_hash"])
    op.create_index("ix_one_time_tokens_expires_at", "one_time_tokens", ["expires_at"])


def downgrade() -> None:
    op.drop_table("one_time_tokens")
    op.drop_table("auth_sessions")
    for table in ("events", "tasks", "goals", "habits", "balance_assessments", "recommendations", "chat_messages"):
        op.drop_index(f"ix_{table}_demo_seed_key", table_name=table)
        op.drop_column(table, "demo_seed_key")
    op.drop_column("user_settings", "ai_context_consent_revoked_at")
    op.drop_column("user_settings", "ai_context_consent_at")
    op.drop_column("user_settings", "ai_context_consent_version")
    op.drop_column("users", "sessions_revoked_at")
    op.drop_column("users", "email_verified_at")

    if op.get_bind().dialect.name == "postgresql":
        for table, columns in TIMESTAMP_COLUMNS.items():
            for column in columns:
                op.alter_column(
                    table,
                    column,
                    existing_type=sa.DateTime(timezone=True),
                    type_=sa.DateTime(),
                    postgresql_using=f"{column} AT TIME ZONE 'UTC'",
                )
