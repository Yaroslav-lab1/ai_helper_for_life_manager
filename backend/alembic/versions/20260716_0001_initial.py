"""Initial Axel One schema."""

from alembic import op
import sqlalchemy as sa

revision = "20260716_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("users",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False), sa.Column("name", sa.String(120), nullable=False),
        sa.Column("timezone", sa.String(80), nullable=False), sa.Column("occupation", sa.String(160), nullable=True),
        sa.Column("avatar_color", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("email"))
    op.create_index("ix_users_email", "users", ["email"])
    op.create_table("user_settings",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("theme", sa.String(20), nullable=False), sa.Column("language", sa.String(10), nullable=False),
        sa.Column("notifications_enabled", sa.Boolean(), nullable=False), sa.Column("daily_digest_time", sa.String(5), nullable=False),
        sa.Column("workday_start", sa.String(5), nullable=False), sa.Column("workday_end", sa.String(5), nullable=False),
        sa.Column("weekly_focus_hours", sa.Integer(), nullable=False), sa.Column("compact_mode", sa.Boolean(), nullable=False),
        sa.Column("ai_tone", sa.String(30), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_table("events",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False), sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(), nullable=False), sa.Column("end_at", sa.DateTime(), nullable=False),
        sa.Column("category", sa.String(40), nullable=False), sa.Column("color", sa.String(20), nullable=False),
        sa.Column("location", sa.String(255), nullable=True), sa.Column("recurrence_rule", sa.String(255), nullable=True),
        sa.Column("reminder_minutes", sa.Integer(), nullable=True), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_events_user_id", "events", ["user_id"]); op.create_index("ix_events_start_at", "events", ["start_at"])
    op.create_table("tasks",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(), nullable=True), sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("estimate_minutes", sa.Integer(), nullable=False),
        sa.Column("energy", sa.String(20), nullable=False), sa.Column("project", sa.String(100), nullable=True),
        sa.Column("reminder_at", sa.DateTime(), nullable=True), sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_tasks_user_id", "tasks", ["user_id"]); op.create_index("ix_tasks_due_at", "tasks", ["due_at"]); op.create_index("ix_tasks_status", "tasks", ["status"])
    op.create_table("goals",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("description", sa.Text(), nullable=True),
        sa.Column("horizon", sa.String(30), nullable=False), sa.Column("target_date", sa.Date(), nullable=True),
        sa.Column("progress", sa.Integer(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_goals_user_id", "goals", ["user_id"])
    op.create_table("goal_steps",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("goal_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(240), nullable=False), sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=True), sa.Column("is_completed", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"))
    op.create_index("ix_goal_steps_goal_id", "goal_steps", ["goal_id"])
    op.create_table("habits",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False), sa.Column("emoji", sa.String(12), nullable=False),
        sa.Column("cadence", sa.String(20), nullable=False), sa.Column("target_per_week", sa.Integer(), nullable=False),
        sa.Column("color", sa.String(20), nullable=False), sa.Column("archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_habits_user_id", "habits", ["user_id"])
    op.create_table("habit_checkins",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("checkin_date", sa.Date(), nullable=False), sa.Column("value", sa.Float(), nullable=False),
        sa.Column("note", sa.String(255), nullable=True), sa.ForeignKeyConstraint(["habit_id"], ["habits.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("habit_id", "checkin_date", name="uq_habit_checkin_date"))
    op.create_index("ix_habit_checkins_habit_id", "habit_checkins", ["habit_id"])
    op.create_table("balance_assessments",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("assessment_date", sa.Date(), nullable=False), sa.Column("health", sa.Integer(), nullable=False),
        sa.Column("career", sa.Integer(), nullable=False), sa.Column("finance", sa.Integer(), nullable=False),
        sa.Column("relationships", sa.Integer(), nullable=False), sa.Column("growth", sa.Integer(), nullable=False),
        sa.Column("recreation", sa.Integer(), nullable=False), sa.Column("environment", sa.Integer(), nullable=False),
        sa.Column("contribution", sa.Integer(), nullable=False), sa.Column("note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_balance_assessments_user_id", "balance_assessments", ["user_id"])
    op.create_table("recommendations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False), sa.Column("action", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_table("chat_messages",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False), sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"))
    op.create_index("ix_chat_messages_user_id", "chat_messages", ["user_id"])


def downgrade() -> None:
    for table in ["chat_messages", "recommendations", "balance_assessments", "habit_checkins", "habits", "goal_steps", "goals", "tasks", "events", "user_settings", "users"]:
        op.drop_table(table)
