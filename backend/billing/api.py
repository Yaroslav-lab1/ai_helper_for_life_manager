from __future__ import annotations

from ipaddress import ip_address, ip_network

from fastapi import APIRouter, HTTPException, Request, status

from backend.api.deps import CurrentUser, DbSession
from backend.billing.catalog import catalog_payload
from backend.billing.entitlements import get_or_create_subscription
from backend.billing.schemas import (
    BillingActionResponse,
    ChangePlanRequest,
    CheckoutRequest,
    CheckoutResponse,
    PaymentResponse,
    SubscriptionResponse,
)
from backend.billing.service import (
    WebhookVerificationError,
    billing_availability,
    cancel_subscription,
    change_plan,
    checkout,
    ensure_billing_available,
    get_owned_payment,
    process_webhook,
    resume_subscription,
    serialize_payment,
    serialize_subscription,
)
from backend.billing.yookassa_client import BillingProviderError, get_billing_client
from backend.config import settings
from backend.services.rate_limit import client_ip

router = APIRouter(prefix="/billing", tags=["Billing & subscriptions"])
YOOKASSA_WEBHOOK_NETWORKS = tuple(
    ip_network(value)
    for value in (
        "185.71.76.0/27",
        "185.71.77.0/27",
        "77.75.153.0/25",
        "77.75.156.11/32",
        "77.75.156.35/32",
        "77.75.154.128/25",
        "2a02:5180::/32",
    )
)


@router.get("/plans")
def list_plans():
    checkout_available, checkout_unavailable_message = billing_availability()
    return {
        "plans": catalog_payload(),
        "checkout_available": checkout_available,
        "checkout_unavailable_message": checkout_unavailable_message,
    }


@router.get("/subscription", response_model=SubscriptionResponse)
def subscription(user: CurrentUser, db: DbSession):
    item = get_or_create_subscription(db, user.id)
    db.commit()
    return serialize_subscription(item)


@router.post("/checkout", response_model=CheckoutResponse, status_code=status.HTTP_201_CREATED)
def create_checkout(payload: CheckoutRequest, user: CurrentUser, db: DbSession):
    # Validate configuration before constructing the SDK client. Otherwise a
    # disabled or incomplete provider configuration escapes as an opaque 500.
    ensure_billing_available()
    try:
        client = get_billing_client()
    except BillingProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "billing_not_configured", "message": "Платёжный провайдер не настроен."},
        ) from exc
    payment = checkout(db, user, payload.plan_code, payload.billing_interval, client)
    return {"payment_id": payment.id, "confirmation_url": payment.confirmation_url}


@router.get("/payments/{payment_id}", response_model=PaymentResponse)
def payment_status(payment_id: int, user: CurrentUser, db: DbSession):
    return serialize_payment(get_owned_payment(db, user.id, payment_id))


@router.post("/cancel", response_model=BillingActionResponse)
def cancel(user: CurrentUser, db: DbSession):
    item = cancel_subscription(db, user)
    return {
        "subscription": serialize_subscription(item),
        "message": "Автопродление отключено. Доступ сохранится до конца оплаченного периода.",
    }


@router.post("/resume", response_model=BillingActionResponse)
def resume(user: CurrentUser, db: DbSession):
    item = resume_subscription(db, user)
    return {
        "subscription": serialize_subscription(item),
        "message": "Автопродление возобновлено.",
    }


@router.post("/change-plan", response_model=BillingActionResponse)
def schedule_change(payload: ChangePlanRequest, user: CurrentUser, db: DbSession):
    item = change_plan(db, user, payload.plan_code, payload.billing_interval)
    return {
        "subscription": serialize_subscription(item),
        "message": "Новый тариф будет применён со следующего расчётного периода.",
    }


def _verify_webhook_ip(request: Request) -> None:
    if not settings.yookassa_webhook_ip_check_enabled:
        return
    try:
        address = ip_address(client_ip(request))
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Webhook source is not allowed") from exc
    if not any(address in network for network in YOOKASSA_WEBHOOK_NETWORKS):
        raise HTTPException(status_code=403, detail="Webhook source is not allowed")


@router.post("/yookassa/webhook")
async def yookassa_webhook(request: Request, db: DbSession):
    _verify_webhook_ip(request)
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON notification") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid notification")
    try:
        process_webhook(db, payload, get_billing_client())
    except WebhookVerificationError as exc:
        raise HTTPException(status_code=400, detail="Webhook verification failed") from exc
    except BillingProviderError as exc:
        raise HTTPException(status_code=502, detail="Provider verification unavailable") from exc
    return {"status": "ok"}
