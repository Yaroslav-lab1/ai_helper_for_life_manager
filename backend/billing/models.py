from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.session import Base
from backend.database.types import UTCDateTime
from backend.services.time import utc_now


class UserSubscription(Base):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_user_subscriptions_user_id"),
        CheckConstraint("plan_code IN ('free','pro','executive')", name="ck_user_subscriptions_plan"),
        CheckConstraint(
            "status IN ('free','pending','active','past_due','cancel_scheduled','canceled','expired')",
            name="ck_user_subscriptions_status",
        ),
        CheckConstraint(
            "billing_interval IS NULL OR billing_interval IN ('monthly','yearly')",
            name="ck_user_subscriptions_interval",
        ),
        Index("ix_user_subscriptions_due", "status", "current_period_end"),
        Index("ix_user_subscriptions_retry", "status", "next_retry_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    plan_code: Mapped[str] = mapped_column(String(24), default="free", nullable=False)
    billing_interval: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="free", nullable=False)
    current_period_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    current_period_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    scheduled_plan_code: Mapped[str | None] = mapped_column(String(24), nullable=True)
    scheduled_billing_interval: Mapped[str | None] = mapped_column(String(16), nullable=True)
    yookassa_payment_method_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="subscription")
    payments: Mapped[list["BillingPayment"]] = relationship(back_populates="subscription")


class BillingPayment(Base):
    __tablename__ = "billing_payments"
    __table_args__ = (
        UniqueConstraint("provider_payment_id", name="uq_billing_payments_provider_payment_id"),
        UniqueConstraint("idempotence_key", name="uq_billing_payments_idempotence_key"),
        UniqueConstraint(
            "subscription_id", "kind", "period_start", name="uq_billing_payments_renewal_period"
        ),
        CheckConstraint("kind IN ('initial','renewal')", name="ck_billing_payments_kind"),
        CheckConstraint("plan_code IN ('pro','executive')", name="ck_billing_payments_plan"),
        CheckConstraint("billing_interval IN ('monthly','yearly')", name="ck_billing_payments_interval"),
        CheckConstraint(
            "status IN ('created','pending','waiting_for_capture','processing','retry','succeeded','canceled','refunded')",
            name="ck_billing_payments_status",
        ),
        CheckConstraint("amount >= 0", name="ck_billing_payments_amount"),
        Index("ix_billing_payments_user_created", "user_id", "created_at"),
        Index("ix_billing_payments_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subscription_id: Mapped[int | None] = mapped_column(
        ForeignKey("user_subscriptions.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(24), default="yookassa", nullable=False)
    provider_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    idempotence_key: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    plan_code: Mapped[str] = mapped_column(String(24), nullable=False)
    plan_name: Mapped[str] = mapped_column(String(80), nullable=False)
    billing_interval: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="created", nullable=False)
    description: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmation_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method_saved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    period_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(), default=utc_now, onupdate=utc_now, nullable=False
    )

    user = relationship("User", back_populates="billing_payments")
    subscription: Mapped[UserSubscription | None] = relationship(back_populates="payments")


class BillingWebhookEvent(Base):
    __tablename__ = "billing_webhook_events"
    __table_args__ = (
        UniqueConstraint("event_key", name="uq_billing_webhook_events_event_key"),
        CheckConstraint(
            "processing_status IN ('received','processing','processed','failed')",
            name="ck_billing_webhook_events_status",
        ),
        Index("ix_billing_webhook_events_received", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(24), default="yookassa", nullable=False)
    event_key: Mapped[str] = mapped_column(String(180), nullable=False)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    provider_object_id: Mapped[str] = mapped_column(String(64), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(24), default="received", nullable=False)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_class: Mapped[str | None] = mapped_column(String(120), nullable=True)
