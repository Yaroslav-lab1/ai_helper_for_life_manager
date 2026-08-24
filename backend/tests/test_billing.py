from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.billing.catalog import catalog_payload, get_plan
from backend.billing.entitlements import has_entitlement
from backend.billing.models import BillingPayment, BillingWebhookEvent, UserSubscription
from backend.billing.service import add_billing_period, process_due_subscription
from backend.billing.yookassa_client import (
    BillingProviderError,
    FakeYooKassaClient,
    ProviderPayment,
    set_billing_client_for_tests,
)
from backend.config import Settings, settings
from backend.database import SessionLocal
from backend.models import User
from backend.services.time import utc_now


def register(client: TestClient, email: str = "billing@example.com") -> tuple[dict[str, str], dict]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "billing-secure-password", "name": "Billing User"},
    )
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, response.json()["user"]


@pytest.fixture
def billing_provider():
    previous = (
        settings.yookassa_enabled,
        settings.yookassa_shop_id,
        settings.yookassa_secret_key,
        settings.yookassa_receipt_mode,
        settings.subscription_retry_delays_hours,
        settings.subscription_grace_period_days,
    )
    settings.yookassa_enabled = True
    settings.yookassa_shop_id = "test-shop"
    settings.yookassa_secret_key = "test_secret"
    settings.yookassa_receipt_mode = "disabled"
    settings.subscription_retry_delays_hours = "24,72"
    settings.subscription_grace_period_days = 3
    fake = FakeYooKassaClient()
    set_billing_client_for_tests(fake)
    yield fake
    (
        settings.yookassa_enabled,
        settings.yookassa_shop_id,
        settings.yookassa_secret_key,
        settings.yookassa_receipt_mode,
        settings.subscription_retry_delays_hours,
        settings.subscription_grace_period_days,
    ) = previous
    set_billing_client_for_tests(None)


def checkout(client: TestClient, headers: dict[str, str], plan: str = "pro", interval: str = "monthly"):
    response = client.post(
        "/api/v1/billing/checkout",
        headers=headers,
        json={"plan_code": plan, "billing_interval": interval},
    )
    assert response.status_code == 201, response.text
    return response.json()


def provider_succeeds(fake: FakeYooKassaClient, provider_id: str, *, method: str = "pm_safe"):
    fake.payments[provider_id] = replace(
        fake.payments[provider_id],
        status="succeeded",
        paid=True,
        payment_method_id=method,
        payment_method_saved=True,
    )


def notify(client: TestClient, event: str, provider_id: str, *, object_data: dict | None = None):
    body = object_data or {"id": provider_id, "status": event.split(".")[-1]}
    return client.post(
        "/api/v1/billing/yookassa/webhook",
        json={"type": "notification", "event": event, "object": body},
    )


def test_new_user_gets_free_subscription_and_catalog_uses_exact_decimal_prices(client: TestClient):
    headers, _ = register(client)
    subscription = client.get("/api/v1/billing/subscription", headers=headers)
    assert subscription.status_code == 200
    assert subscription.json()["plan_code"] == "free"
    assert subscription.json()["status"] == "free"
    assert {"calendar", "tasks", "goals", "habits", "basic_analytics"} <= set(
        subscription.json()["entitlements"]
    )
    plans = {item["code"]: item for item in catalog_payload()}
    assert plans["pro"]["monthly_price"] == "399.00"
    assert plans["pro"]["yearly_price"] == "3974.04"
    assert plans["executive"]["yearly_price"] == "9860.40"
    assert get_plan("pro").price("yearly") == Decimal("3974.04")
    assert add_billing_period(datetime(2027, 1, 31, 10, tzinfo=UTC), "monthly") == datetime(
        2027, 2, 28, 10, tzinfo=UTC
    )


def test_disabled_billing_is_reported_before_checkout(client: TestClient):
    previous = settings.yookassa_enabled
    settings.yookassa_enabled = False
    try:
        catalog = client.get("/api/v1/billing/plans")
        assert catalog.status_code == 200
        assert catalog.json()["checkout_available"] is False
        assert catalog.json()["checkout_unavailable_message"] == "Оплата временно отключена администратором."

        headers, _ = register(client, "billing-disabled@example.com")
        response = client.post(
            "/api/v1/billing/checkout",
            headers=headers,
            json={"plan_code": "pro", "billing_interval": "monthly"},
        )
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "code": "billing_disabled",
            "message": "Оплата временно отключена администратором.",
        }
    finally:
        settings.yookassa_enabled = previous


def test_enabled_billing_is_exposed_in_catalog(client: TestClient, billing_provider: FakeYooKassaClient):
    catalog = client.get("/api/v1/billing/plans")
    assert catalog.status_code == 200
    assert catalog.json()["checkout_available"] is True
    assert catalog.json()["checkout_unavailable_message"] is None


def test_checkout_rejects_client_amount_and_creates_redirect_with_saved_method(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, _ = register(client)
    tampered = client.post(
        "/api/v1/billing/checkout",
        headers=headers,
        json={"plan_code": "pro", "billing_interval": "monthly", "amount": "1.00"},
    )
    assert tampered.status_code == 422
    result = checkout(client, headers)
    assert result["confirmation_url"] == "https://yookassa.test/confirm"
    kind, payload, key = billing_provider.create_calls[0]
    assert kind == "initial"
    assert payload["amount"] == {"value": "399.00", "currency": "RUB"}
    assert payload["capture"] is True
    assert payload["confirmation"]["type"] == "redirect"
    assert payload["save_payment_method"] is True
    assert "receipt" not in payload
    assert key == f"checkout:{result['payment_id']}" and len(key) <= 64


def test_checkout_network_retry_reuses_internal_payment_and_idempotence_key(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, _ = register(client)
    billing_provider.error = BillingProviderError("ReadTimeout", retryable=True)
    first = client.post(
        "/api/v1/billing/checkout",
        headers=headers,
        json={"plan_code": "pro", "billing_interval": "monthly"},
    )
    assert first.status_code == 502
    billing_provider.error = None
    second = checkout(client, headers)
    assert [call[2] for call in billing_provider.create_calls] == [
        f"checkout:{second['payment_id']}",
        f"checkout:{second['payment_id']}",
    ]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BillingPayment)) == 1


def test_open_checkout_cannot_create_a_second_payment_for_another_plan(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, _ = register(client)
    checkout(client, headers, "pro", "monthly")
    second = client.post(
        "/api/v1/billing/checkout",
        headers=headers,
        json={"plan_code": "executive", "billing_interval": "yearly"},
    )
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "checkout_in_progress"
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BillingPayment)) == 1
    assert len(billing_provider.create_calls) == 1


def test_return_poll_does_not_activate_but_verified_webhook_does_once(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, user = register(client)
    result = checkout(client, headers, "pro", "yearly")
    provider_id = next(iter(billing_provider.payments))
    provider_succeeds(billing_provider, provider_id)

    polled = client.get(f"/api/v1/billing/payments/{result['payment_id']}", headers=headers)
    assert polled.json()["status"] == "pending"
    assert client.get("/api/v1/billing/subscription", headers=headers).json()["plan_code"] == "free"

    first = notify(client, "payment.succeeded", provider_id)
    second = notify(client, "payment.succeeded", provider_id)
    assert first.status_code == second.status_code == 200
    active = client.get("/api/v1/billing/subscription", headers=headers).json()
    assert active["plan_code"] == "pro" and active["status"] == "active"
    assert active["billing_interval"] == "yearly"
    with SessionLocal() as db:
        subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user["id"]))
        assert subscription.yookassa_payment_method_id == "pm_safe"
        assert db.scalar(select(func.count()).select_from(BillingWebhookEvent)) == 1
        payment = db.get(BillingPayment, result["payment_id"])
        assert payment.period_end.year == payment.period_start.year + 1


def test_webhook_rejects_fake_status_amount_and_metadata(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, _ = register(client)
    checkout(client, headers)
    provider_id = next(iter(billing_provider.payments))
    pending = notify(client, "payment.succeeded", provider_id)
    assert pending.status_code == 400

    original = billing_provider.payments[provider_id]
    billing_provider.payments[provider_id] = replace(
        original, status="succeeded", paid=True, amount=Decimal("1.00")
    )
    assert notify(client, "payment.succeeded", provider_id).status_code == 400
    billing_provider.payments[provider_id] = replace(
        original, status="succeeded", paid=True, metadata={**original.metadata, "plan_code": "executive"}
    )
    assert notify(client, "payment.succeeded", provider_id).status_code == 400
    assert client.get("/api/v1/billing/subscription", headers=headers).json()["plan_code"] == "free"


def test_canceled_payment_does_not_activate(client: TestClient, billing_provider: FakeYooKassaClient):
    headers, _ = register(client)
    result = checkout(client, headers)
    provider_id = next(iter(billing_provider.payments))
    billing_provider.payments[provider_id] = replace(
        billing_provider.payments[provider_id], status="canceled", cancellation_reason="insufficient_funds"
    )
    assert notify(client, "payment.canceled", provider_id).status_code == 200
    assert client.get(f"/api/v1/billing/payments/{result['payment_id']}", headers=headers).json()["status"] == "canceled"
    assert client.get("/api/v1/billing/subscription", headers=headers).json()["effective_plan_code"] == "free"


def test_payment_endpoint_is_user_scoped(client: TestClient, billing_provider: FakeYooKassaClient):
    first, _ = register(client, "owner@example.com")
    second, _ = register(client, "other@example.com")
    result = checkout(client, first)
    assert client.get(f"/api/v1/billing/payments/{result['payment_id']}", headers=second).status_code == 404


def _activate(db, user_id: int, plan: str = "pro", *, due=False, method="pm_renew") -> UserSubscription:
    subscription = db.scalar(select(UserSubscription).where(UserSubscription.user_id == user_id))
    now = utc_now()
    subscription.plan_code = plan
    subscription.billing_interval = "monthly"
    subscription.status = "active"
    subscription.current_period_start = now - timedelta(days=31)
    subscription.current_period_end = now - timedelta(minutes=1) if due else now + timedelta(days=10)
    subscription.yookassa_payment_method_id = method
    db.commit()
    return subscription


def test_cancel_resume_and_scheduled_change_preserve_current_access(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, user = register(client)
    with SessionLocal() as db:
        _activate(db, user["id"])
    canceled = client.post("/api/v1/billing/cancel", headers=headers)
    assert canceled.status_code == 200
    assert canceled.json()["subscription"]["effective_plan_code"] == "pro"
    assert canceled.json()["subscription"]["cancel_at_period_end"] is True
    resumed = client.post("/api/v1/billing/resume", headers=headers)
    assert resumed.status_code == 200 and resumed.json()["subscription"]["status"] == "active"
    changed = client.post(
        "/api/v1/billing/change-plan",
        headers=headers,
        json={"plan_code": "executive", "billing_interval": "yearly"},
    )
    assert changed.status_code == 200
    assert changed.json()["subscription"]["plan_code"] == "pro"
    assert changed.json()["subscription"]["scheduled_plan_code"] == "executive"


def test_entitlements_free_pro_and_executive(client: TestClient):
    free_headers, free_user = register(client, "free@example.com")
    assert client.post("/api/v1/ai/chat", headers=free_headers, json={"message": "test"}).status_code == 403
    detail = client.post("/api/v1/ai/chat", headers=free_headers, json={"message": "test"}).json()["detail"]
    assert detail["code"] == "subscription_required" and detail["required_plan"] == "pro"
    with SessionLocal() as db:
        user = db.get(User, free_user["id"])
        subscription = _activate(db, user.id, "pro")
        assert has_entitlement(user, "ai_assistant", db)
        assert not has_entitlement(user, "life_report", db)
    assert client.get("/api/v1/overload", headers=free_headers).status_code == 200
    with SessionLocal() as db:
        subscription = db.scalar(
            select(UserSubscription).where(UserSubscription.user_id == free_user["id"])
        )
        subscription.plan_code = "executive"
        db.commit()
        user = db.get(User, free_user["id"])
        assert has_entitlement(user, "life_report", db)
    assert client.get("/api/v1/overload", headers=free_headers).status_code == 200


def test_renewal_is_created_once_and_success_moves_calendar_period(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    _, user = register(client)
    with SessionLocal() as db:
        subscription = _activate(db, user["id"], due=True)
        original_end = subscription.current_period_end
        subscription_id = subscription.id
    with SessionLocal() as db:
        assert process_due_subscription(db, subscription_id, billing_provider)
    with SessionLocal() as db:
        assert not process_due_subscription(db, subscription_id, billing_provider)
        assert db.scalar(select(func.count()).select_from(BillingPayment)) == 1
        payment = db.scalar(select(BillingPayment))
        provider_id = payment.provider_payment_id
    provider_succeeds(billing_provider, provider_id)
    with SessionLocal() as db:
        assert process_due_subscription(db, subscription_id, billing_provider)
        subscription = db.get(UserSubscription, subscription_id)
        assert subscription.status == "active"
        assert subscription.current_period_start == original_end
        assert subscription.current_period_end > original_end
    assert len(billing_provider.create_calls) == 1


def test_two_workers_do_not_create_duplicate_renewal(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    _, user = register(client, "parallel@example.com")
    with SessionLocal() as db:
        subscription_id = _activate(db, user["id"], due=True).id

    def run_once():
        with SessionLocal() as db:
            return process_due_subscription(db, subscription_id, billing_provider)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run_once(), range(2)))
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(BillingPayment)) == 1
    assert len(billing_provider.create_calls) == 1


def test_failed_renewal_retries_keeps_grace_then_downgrades(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    _, user = register(client)
    settings.subscription_retry_delays_hours = "1,2"
    with SessionLocal() as db:
        subscription = _activate(db, user["id"], due=True)
        subscription.current_period_end = utc_now() - timedelta(days=4)
        db.commit()
        subscription_id = subscription.id
    billing_provider.error = BillingProviderError("ReadTimeout", retryable=True)
    for _ in range(3):
        with SessionLocal() as db:
            subscription = db.get(UserSubscription, subscription_id)
            subscription.next_retry_at = utc_now() - timedelta(seconds=1)
            db.commit()
            process_due_subscription(db, subscription_id, billing_provider)
    with SessionLocal() as db:
        subscription = db.get(UserSubscription, subscription_id)
        assert subscription.plan_code == "free" and subscription.status == "free"
        assert db.scalar(select(func.count()).select_from(BillingPayment)) == 1


def test_full_refund_preserves_access_and_schedules_end(
    client: TestClient, billing_provider: FakeYooKassaClient
):
    headers, _ = register(client)
    checkout(client, headers)
    provider_id = next(iter(billing_provider.payments))
    provider_succeeds(billing_provider, provider_id)
    assert notify(client, "payment.succeeded", provider_id).status_code == 200
    billing_provider.payments[provider_id] = replace(
        billing_provider.payments[provider_id], refunded_amount=Decimal("399.00")
    )
    response = notify(
        client,
        "refund.succeeded",
        provider_id,
        object_data={"id": "refund-1", "payment_id": provider_id, "status": "succeeded"},
    )
    assert response.status_code == 200
    subscription = client.get("/api/v1/billing/subscription", headers=headers).json()
    assert subscription["effective_plan_code"] == "pro"
    assert subscription["cancel_at_period_end"] is True


def test_production_billing_validation_rejects_test_keys_http_and_legacy_self_employed_mode():
    base = dict(
        _env_file=None,
        environment="production",
        database_url="postgresql+psycopg://axel:unique-random-db-password@db/axel",
        secret_key="a-unique-random-secret-key-with-more-than-32-characters",
        domain="example.com",
        trusted_hosts="example.com",
        cors_origins="https://example.com",
        email_backend="smtp",
        smtp_host="smtp.example.com",
        email_from="noreply@example.com",
        use_secure_auth_cookies=True,
        notification_worker_enabled=True,
        llm_provider="ollama",
        yookassa_enabled=True,
        yookassa_shop_id="123456",
        yookassa_return_url="https://example.com/billing/return",
        yookassa_receipt_mode="external",
    )
    with pytest.raises(RuntimeError, match="non-test YOOKASSA_SECRET_KEY"):
        Settings(**base, yookassa_secret_key="test_example").validate_runtime()
    with pytest.raises(RuntimeError, match="HTTPS"):
        Settings(
            **{**base, "yookassa_return_url": "http://example.com/billing/return"},
            yookassa_secret_key="live-secret-value",
        ).validate_runtime()
    with pytest.raises(RuntimeError, match="discontinued"):
        Settings(
            **{**base, "yookassa_receipt_mode": "self_employed"},
            yookassa_secret_key="live-secret-value",
        ).validate_runtime()
    Settings(**base, yookassa_secret_key="live-secret-value").validate_runtime()
