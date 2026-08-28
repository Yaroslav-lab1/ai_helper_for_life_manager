from __future__ import annotations

import calendar
import hashlib
import hmac
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.billing.catalog import BILLING_INTERVALS, MONEY, get_plan
from backend.billing.entitlements import effective_plan_code, get_or_create_subscription
from backend.billing.models import BillingPayment, BillingWebhookEvent, UserSubscription
from backend.billing.yookassa_client import BillingClient, BillingProviderError, ProviderPayment
from backend.config import settings
from backend.models.entities import NotificationDelivery, User
from backend.services.time import utc_now

ALLOWED_WEBHOOK_EVENTS = {
    "payment.succeeded",
    "payment.canceled",
    "payment.waiting_for_capture",
    "refund.succeeded",
}
TERMINAL_SUCCESS_STATUSES = {"succeeded", "refunded"}
OPEN_PAYMENT_STATUSES = {"created", "pending", "waiting_for_capture", "processing", "retry"}

logger = logging.getLogger(__name__)


class WebhookVerificationError(ValueError):
    pass


def _billing_error(code: str, message: str, http_status: int = 409) -> HTTPException:
    return HTTPException(status_code=http_status, detail={"code": code, "message": message})


def _provider_checkout_message(exc: BillingProviderError) -> str:
    if exc.code.startswith("UnauthorizedError"):
        return "ЮKassa отклонила shopId или секретный ключ. Проверьте реквизиты магазина."
    if exc.code.startswith("ForbiddenError"):
        return "ЮKassa приняла ключ, но магазину недоступно создание платежей."
    if exc.code.startswith("BadRequestError"):
        if exc.code.endswith(":receipt") or ":receipt." in exc.code:
            return "ЮKassa требует корректные данные чека. Проверьте настройку фискализации магазина."
        return "ЮKassa отклонила параметры платежа. Проверьте настройки магазина и чеков."
    return "ЮKassa временно не ответила. Повторите попытку."


def ensure_billing_available() -> None:
    if not settings.yookassa_enabled:
        raise _billing_error(
            "billing_disabled", "Оплата временно отключена администратором.", status.HTTP_503_SERVICE_UNAVAILABLE
        )
    if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
        raise _billing_error(
            "billing_not_configured", "Платёжный провайдер не настроен.", status.HTTP_503_SERVICE_UNAVAILABLE
        )
    if settings.yookassa_receipt_mode == "self_employed":
        raise _billing_error(
            "receipt_mode_unavailable",
            "Режим чеков ЮKassa для самозанятых больше не поддерживается; требуется внешняя схема чеков.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if settings.yookassa_receipt_mode == "54fz" and (
        not settings.yookassa_vat_code.isdigit() or not settings.yookassa_tax_system_code.isdigit()
    ):
        raise _billing_error(
            "receipt_not_configured", "Для режима 54-ФЗ не настроены фискальные параметры.", 503
        )


def billing_availability() -> tuple[bool, str | None]:
    """Expose checkout readiness without leaking provider credentials."""
    try:
        ensure_billing_available()
    except HTTPException as exc:
        detail = exc.detail
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return False, detail["message"]
        return False, "Оплата временно недоступна."
    return True, None


def add_billing_period(value: datetime, interval: str) -> datetime:
    if interval not in BILLING_INTERVALS:
        raise ValueError("Unsupported billing interval")
    months = 1 if interval == "monthly" else 12
    target_index = value.month - 1 + months
    year = value.year + target_index // 12
    month = target_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _user_ref(user_id: int) -> str:
    digest = hmac.new(settings.secret_key.encode(), str(user_id).encode(), hashlib.sha256).hexdigest()
    return digest[:32]


def _expected_metadata(payment: BillingPayment) -> dict[str, str]:
    return {
        "internal_payment_id": str(payment.id),
        "subscription_id": str(payment.subscription_id),
        "user_ref": _user_ref(payment.user_id),
        "plan_code": payment.plan_code,
        "billing_interval": payment.billing_interval,
        "kind": payment.kind,
    }


def _receipt(user: User, payment: BillingPayment) -> dict | None:
    if settings.yookassa_receipt_mode != "54fz":
        return None
    return {
        "customer": {"email": user.email},
        "tax_system_code": int(settings.yookassa_tax_system_code),
        "items": [
            {
                "description": payment.description[:128],
                "quantity": "1.00",
                "amount": {"value": f"{payment.amount:.2f}", "currency": payment.currency},
                "vat_code": int(settings.yookassa_vat_code),
                "payment_subject": settings.yookassa_payment_subject,
                "payment_mode": settings.yookassa_payment_mode,
            }
        ],
    }


def _provider_payload(payment: BillingPayment, user: User, *, recurring: bool) -> dict:
    payload: dict = {
        "amount": {"value": f"{payment.amount:.2f}", "currency": payment.currency},
        "capture": settings.yookassa_capture,
        "description": payment.description,
        "metadata": _expected_metadata(payment),
        "merchant_customer_id": _user_ref(user.id),
    }
    if recurring:
        subscription = payment.subscription
        if subscription is None or not subscription.yookassa_payment_method_id:
            raise BillingProviderError("payment_method_missing")
        payload["payment_method_id"] = subscription.yookassa_payment_method_id
    else:
        payload.update(
            {
                "confirmation": {"type": "redirect", "return_url": settings.yookassa_return_url},
            }
        )
        if settings.yookassa_recurring_payments_enabled:
            payload["save_payment_method"] = True
    receipt = _receipt(user, payment)
    if receipt is not None:
        payload["receipt"] = receipt
    return payload


def serialize_payment(payment: BillingPayment) -> dict:
    return {
        "id": payment.id,
        "kind": payment.kind,
        "plan_code": payment.plan_code,
        "plan_name": payment.plan_name,
        "billing_interval": payment.billing_interval,
        "amount": f"{payment.amount:.2f}",
        "currency": payment.currency,
        "status": payment.status,
        "confirmation_url": payment.confirmation_url,
        "paid_at": payment.paid_at,
        "canceled_at": payment.canceled_at,
        "failure_code": payment.failure_code,
    }


def serialize_subscription(subscription: UserSubscription) -> dict:
    effective = effective_plan_code(subscription)
    plan = get_plan(effective, require_available=False)
    renews = (
        subscription.current_period_end
        if effective != "free" and not subscription.cancel_at_period_end and subscription.status != "past_due"
        else None
    )
    access_until = subscription.current_period_end if effective != "free" else None
    return {
        "plan_code": subscription.plan_code,
        "billing_interval": subscription.billing_interval,
        "status": subscription.status,
        "effective_plan_code": effective,
        "entitlements": sorted(plan.entitlements),
        "current_period_start": subscription.current_period_start,
        "current_period_end": subscription.current_period_end,
        "cancel_at_period_end": subscription.cancel_at_period_end,
        "next_billing_at": renews,
        "access_until": access_until,
        "scheduled_plan_code": subscription.scheduled_plan_code,
        "scheduled_billing_interval": subscription.scheduled_billing_interval,
        "scheduled_change_at": subscription.current_period_end
        if subscription.scheduled_plan_code
        else None,
        "can_resume": bool(
            settings.yookassa_recurring_payments_enabled
            and subscription.yookassa_payment_method_id
            and subscription.current_period_end
            and subscription.current_period_end > utc_now()
        ),
        "retry_count": subscription.retry_count,
        "next_retry_at": subscription.next_retry_at,
    }


def checkout(
    db: Session,
    user: User,
    plan_code: str,
    billing_interval: str,
    client: BillingClient,
) -> BillingPayment:
    ensure_billing_available()
    try:
        plan = get_plan(plan_code)
    except ValueError as exc:
        raise _billing_error("invalid_plan", "Тариф недоступен.", 422) from exc
    if plan.code == "free" or billing_interval not in BILLING_INTERVALS:
        raise _billing_error("invalid_plan", "Выберите доступный платный тариф и интервал.", 422)
    subscription = get_or_create_subscription(db, user.id)
    now = utc_now()
    if effective_plan_code(subscription) != "free" and subscription.current_period_end and subscription.current_period_end > now:
        raise _billing_error(
            "change_plan_required",
            "Активный платный тариф меняется со следующего расчётного периода.",
        )

    # Serialize checkout creation for this user in PostgreSQL. The provider call
    # happens after the internal row is committed, so a concurrent request sees
    # and reuses the same operation and its stable idempotence key.
    subscription = db.scalar(
        select(UserSubscription)
        .where(UserSubscription.id == subscription.id)
        .with_for_update()
    ) or subscription

    reusable = db.scalar(
        select(BillingPayment)
        .where(
            BillingPayment.user_id == user.id,
            BillingPayment.kind == "initial",
            BillingPayment.plan_code == plan.code,
            BillingPayment.billing_interval == billing_interval,
            BillingPayment.status.in_(["created", "pending", "waiting_for_capture"]),
        )
        .order_by(BillingPayment.created_at.desc())
    )
    other_open = db.scalar(
        select(BillingPayment.id).where(
            BillingPayment.user_id == user.id,
            BillingPayment.kind == "initial",
            BillingPayment.status.in_(["created", "pending", "waiting_for_capture"]),
            BillingPayment.id != (reusable.id if reusable else -1),
        )
    )
    if other_open is not None:
        raise _billing_error(
            "checkout_in_progress",
            "Сначала завершите или дождитесь отмены уже созданного платежа.",
        )
    if reusable is not None and reusable.confirmation_url:
        return reusable

    if reusable is None:
        payment = BillingPayment(
            user_id=user.id,
            subscription_id=subscription.id,
            idempotence_key=f"new:{uuid4().hex}",
            kind="initial",
            plan_code=plan.code,
            plan_name=plan.name,
            billing_interval=billing_interval,
            amount=plan.price(billing_interval),
            currency=settings.yookassa_currency,
            status="created",
            description=f"Подписка Axel One {plan.name}, {billing_interval}",
        )
        db.add(payment)
        db.flush()
        payment.idempotence_key = f"checkout:{payment.id}"
        db.commit()
        db.refresh(payment)
    else:
        payment = reusable

    try:
        provider = client.create_initial_payment(
            _provider_payload(payment, user, recurring=False), payment.idempotence_key
        )
        _verify_provider_payment(payment, provider)
    except BillingProviderError as exc:
        payment.failure_code = exc.code[:80]
        # Provider 4xx responses are definitive: no payment was created. Closing
        # the internal attempt lets the user correct configuration or choose a
        # different plan. Transport failures remain open so the same stable
        # idempotence key can safely be retried.
        if not exc.retryable:
            payment.status = "canceled"
            payment.canceled_at = now
            if payment.subscription and payment.subscription.plan_code == "free":
                payment.subscription.status = "free"
        db.commit()
        raise _billing_error(
            "provider_unavailable", _provider_checkout_message(exc), 502
        ) from exc
    except WebhookVerificationError as exc:
        payment.failure_code = "provider_response_mismatch"
        db.commit()
        raise _billing_error("provider_response_mismatch", "ЮKassa вернула несогласованные данные.", 502) from exc

    payment.provider_payment_id = provider.id
    payment.confirmation_url = provider.confirmation_url
    if provider.status == "canceled":
        payment.status = "canceled"
        payment.canceled_at = now
        payment.failure_code = (provider.cancellation_reason or "provider_canceled")[:80]
        db.commit()
        raise _billing_error("payment_canceled", "ЮKassa отменила создание платежа.", 502)
    # Even an immediately succeeded create response is not enough to activate access:
    # the public webhook must fetch and verify the current provider object first.
    payment.status = "pending"
    if effective_plan_code(subscription) == "free":
        subscription.status = "pending"
    db.commit()
    db.refresh(payment)
    if not payment.confirmation_url:
        raise _billing_error("confirmation_missing", "ЮKassa не вернула ссылку подтверждения.", 502)
    return payment


def _verify_provider_payment(payment: BillingPayment, provider: ProviderPayment) -> None:
    if payment.provider_payment_id and provider.id != payment.provider_payment_id:
        raise WebhookVerificationError("provider_payment_id_mismatch")
    if provider.amount.quantize(MONEY) != payment.amount.quantize(MONEY):
        raise WebhookVerificationError("amount_mismatch")
    if provider.currency != payment.currency:
        raise WebhookVerificationError("currency_mismatch")
    expected = _expected_metadata(payment)
    if any(provider.metadata.get(key) != value for key, value in expected.items()):
        raise WebhookVerificationError("metadata_mismatch")


def _apply_succeeded(db: Session, payment: BillingPayment, provider: ProviderPayment, now: datetime) -> bool:
    if payment.status in TERMINAL_SUCCESS_STATUSES:
        return False
    subscription = payment.subscription
    if subscription is None:
        raise WebhookVerificationError("subscription_missing")
    start = payment.period_start or now
    end = payment.period_end or add_billing_period(start, payment.billing_interval)
    payment.status = "succeeded"
    payment.paid_at = now
    payment.period_start = start
    payment.period_end = end
    payment.failure_code = None
    payment.confirmation_url = None
    if (
        settings.yookassa_recurring_payments_enabled
        and provider.payment_method_saved
        and provider.payment_method_id
    ):
        payment.payment_method_saved = True
        subscription.yookassa_payment_method_id = provider.payment_method_id[:64]
    subscription.plan_code = payment.plan_code
    subscription.billing_interval = payment.billing_interval
    subscription.current_period_start = start
    subscription.current_period_end = end
    if payment.kind == "initial" and not subscription.yookassa_payment_method_id:
        # The shop may accept ordinary payments before YooKassa grants recurring
        # payment permission. Sell exactly one period and never imply that the
        # card will be charged again.
        subscription.status = "cancel_scheduled"
        subscription.cancel_at_period_end = True
        subscription.scheduled_plan_code = "free"
        subscription.scheduled_billing_interval = None
    else:
        subscription.status = "active"
        subscription.cancel_at_period_end = False
        subscription.scheduled_plan_code = None
        subscription.scheduled_billing_interval = None
    subscription.retry_count = 0
    subscription.next_retry_at = None
    return True


def _apply_canceled(payment: BillingPayment, provider: ProviderPayment, now: datetime) -> bool:
    if payment.status in TERMINAL_SUCCESS_STATUSES:
        return False
    if payment.status == "canceled":
        return False
    payment.status = "canceled"
    payment.canceled_at = now
    payment.failure_code = (provider.cancellation_reason or "provider_canceled")[:80]
    if payment.kind == "initial" and payment.subscription and payment.subscription.plan_code == "free":
        payment.subscription.status = "free"
    return True


def _apply_refund(payment: BillingPayment, provider: ProviderPayment) -> bool:
    if provider.refunded_amount < payment.amount:
        return False
    if payment.status == "refunded":
        return False
    if payment.status != "succeeded":
        raise WebhookVerificationError("refund_for_unpaid_payment")
    payment.status = "refunded"
    # Explicit policy: a full refund does not remove already issued access. It turns
    # off the next renewal and preserves access through current_period_end.
    if payment.subscription and payment.subscription.plan_code != "free":
        payment.subscription.cancel_at_period_end = True
        payment.subscription.status = "cancel_scheduled"
        payment.subscription.scheduled_plan_code = "free"
        payment.subscription.scheduled_billing_interval = None
    return True


def _event_record(db: Session, event_type: str, object_id: str) -> tuple[BillingWebhookEvent, bool]:
    key = f"yookassa:{event_type}:{object_id}"
    existing = db.scalar(select(BillingWebhookEvent).where(BillingWebhookEvent.event_key == key))
    if existing is not None:
        return existing, existing.processing_status == "processed"
    try:
        with db.begin_nested():
            event = BillingWebhookEvent(
                event_key=key,
                event_type=event_type,
                provider_object_id=object_id,
            )
            db.add(event)
            db.flush()
    except IntegrityError:
        event = db.scalar(select(BillingWebhookEvent).where(BillingWebhookEvent.event_key == key))
        if event is None:
            raise
        return event, event.processing_status == "processed"
    db.commit()
    return event, False


def process_webhook(db: Session, payload: dict, client: BillingClient) -> bool:
    if payload.get("type") != "notification" or payload.get("event") not in ALLOWED_WEBHOOK_EVENTS:
        raise WebhookVerificationError("unsupported_notification")
    event_type = str(payload["event"])
    object_data = payload.get("object")
    if not isinstance(object_data, dict) or not object_data.get("id"):
        raise WebhookVerificationError("invalid_object")
    object_id = str(object_data["id"])
    provider_payment_id = (
        str(object_data.get("payment_id")) if event_type == "refund.succeeded" else object_id
    )
    if not provider_payment_id or provider_payment_id == "None":
        raise WebhookVerificationError("payment_id_missing")
    event, duplicate = _event_record(db, event_type, object_id)
    if duplicate:
        return False
    event.processing_status = "processing"
    event.error_class = None
    db.commit()
    try:
        payment = db.scalar(
            select(BillingPayment)
            .where(BillingPayment.provider_payment_id == provider_payment_id)
            .with_for_update()
        )
        if payment is None:
            raise WebhookVerificationError("unknown_payment")
        provider = client.get_payment(provider_payment_id)
        _verify_provider_payment(payment, provider)
        now = utc_now()
        if event_type == "payment.succeeded":
            if provider.status != "succeeded" or not provider.paid:
                raise WebhookVerificationError("provider_status_mismatch")
            changed = _apply_succeeded(db, payment, provider, now)
        elif event_type == "payment.canceled":
            if provider.status != "canceled":
                raise WebhookVerificationError("provider_status_mismatch")
            changed = _apply_canceled(payment, provider, now)
        elif event_type == "payment.waiting_for_capture":
            if provider.status != "waiting_for_capture":
                raise WebhookVerificationError("provider_status_mismatch")
            changed = payment.status not in TERMINAL_SUCCESS_STATUSES
            if changed:
                payment.status = "waiting_for_capture"
        else:
            if object_data.get("status") not in {None, "succeeded"}:
                raise WebhookVerificationError("refund_status_mismatch")
            changed = _apply_refund(payment, provider)
        event.processing_status = "processed"
        event.processed_at = now
        db.commit()
        return changed
    except Exception as exc:
        db.rollback()
        current = db.get(BillingWebhookEvent, event.id)
        if current is not None:
            current.processing_status = "failed"
            current.error_class = type(exc).__name__[:120]
            db.commit()
        raise


def cancel_subscription(db: Session, user: User) -> UserSubscription:
    subscription = get_or_create_subscription(db, user.id)
    if effective_plan_code(subscription) == "free":
        raise _billing_error("no_paid_subscription", "У вас нет активного платного тарифа.")
    subscription.cancel_at_period_end = True
    subscription.status = "cancel_scheduled"
    subscription.scheduled_plan_code = "free"
    subscription.scheduled_billing_interval = None
    db.commit()
    db.refresh(subscription)
    return subscription


def resume_subscription(db: Session, user: User) -> UserSubscription:
    subscription = get_or_create_subscription(db, user.id)
    if (
        effective_plan_code(subscription) == "free"
        or not subscription.cancel_at_period_end
        or not subscription.current_period_end
        or subscription.current_period_end <= utc_now()
    ):
        raise _billing_error("cannot_resume", "Эту подписку уже нельзя возобновить.")
    if not subscription.yookassa_payment_method_id:
        raise _billing_error("payment_method_missing", "Для возобновления нужен сохранённый способ оплаты.")
    subscription.cancel_at_period_end = False
    subscription.status = "active"
    subscription.scheduled_plan_code = None
    subscription.scheduled_billing_interval = None
    db.commit()
    db.refresh(subscription)
    return subscription


def change_plan(
    db: Session, user: User, plan_code: str, billing_interval: str | None
) -> UserSubscription:
    subscription = get_or_create_subscription(db, user.id)
    try:
        target = get_plan(plan_code)
    except ValueError as exc:
        raise _billing_error("invalid_plan", "Тариф недоступен.", 422) from exc
    if target.code == "free":
        return cancel_subscription(db, user)
    if billing_interval not in BILLING_INTERVALS:
        raise _billing_error("billing_interval_required", "Для платного тарифа выберите интервал.", 422)
    if effective_plan_code(subscription) == "free":
        raise _billing_error(
            "checkout_required", "Переход с FREE начинается с нового безопасного платежа.", 409
        )
    if not settings.yookassa_recurring_payments_enabled or not subscription.yookassa_payment_method_id:
        raise _billing_error(
            "checkout_after_period_end",
            "Новый период можно будет оплатить после окончания текущего. Карта не сохранена.",
            409,
        )
    if subscription.plan_code == target.code and subscription.billing_interval == billing_interval:
        raise _billing_error("already_selected", "Этот тариф и интервал уже действуют.")
    subscription.scheduled_plan_code = target.code
    subscription.scheduled_billing_interval = billing_interval
    subscription.cancel_at_period_end = False
    if subscription.status == "cancel_scheduled":
        subscription.status = "active"
    db.commit()
    db.refresh(subscription)
    return subscription


def get_owned_payment(db: Session, user_id: int, payment_id: int) -> BillingPayment:
    payment = db.scalar(
        select(BillingPayment).where(BillingPayment.id == payment_id, BillingPayment.user_id == user_id)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Платёж не найден.")
    return payment


def refresh_owned_payment(
    db: Session,
    user_id: int,
    payment_id: int,
    client: BillingClient,
) -> BillingPayment:
    """Reconcile a user-owned payment with YooKassa using a server-to-server GET.

    Webhooks remain the primary asynchronous path. This authenticated fallback
    makes the return page resilient to delayed or temporarily missed delivery
    without trusting browser parameters or the notification body.
    """
    payment = db.scalar(
        select(BillingPayment)
        .where(BillingPayment.id == payment_id, BillingPayment.user_id == user_id)
        .with_for_update()
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Платёж не найден.")
    if payment.status not in OPEN_PAYMENT_STATUSES or not payment.provider_payment_id:
        return payment
    try:
        provider = client.get_payment(payment.provider_payment_id)
        _verify_provider_payment(payment, provider)
    except BillingProviderError:
        # A status read must stay available while YooKassa is temporarily down;
        # the next browser poll or webhook will retry the authoritative lookup.
        return payment
    except WebhookVerificationError as exc:
        logger.warning(
            "YooKassa payment reconciliation mismatch (payment_id=%s, reason=%s)",
            payment.id,
            str(exc),
        )
        payment.failure_code = "provider_response_mismatch"
        db.commit()
        return payment

    now = utc_now()
    changed = False
    if provider.status == "succeeded" and provider.paid:
        changed = _apply_succeeded(db, payment, provider, now)
        if provider.refunded_amount >= payment.amount:
            changed = _apply_refund(payment, provider) or changed
    elif provider.status == "canceled":
        changed = _apply_canceled(payment, provider, now)
    elif provider.status == "waiting_for_capture" and payment.status not in TERMINAL_SUCCESS_STATUSES:
        changed = payment.status != "waiting_for_capture"
        payment.status = "waiting_for_capture"
    if changed:
        db.commit()
        db.refresh(payment)
    return payment


def _enqueue_payment_issue(db: Session, subscription: UserSubscription, now: datetime) -> None:
    dedupe = f"billing-past-due:{subscription.id}:{subscription.current_period_end}:{subscription.retry_count}"
    if db.scalar(select(NotificationDelivery.id).where(NotificationDelivery.dedupe_key == dedupe)):
        return
    try:
        with db.begin_nested():
            db.add(
                NotificationDelivery(
                    user_id=subscription.user_id,
                    kind="billing_payment_issue",
                    dedupe_key=dedupe,
                    subject="Не удалось продлить подписку Axel One",
                    body="Проверьте способ оплаты. Во время льготного периода доступ сохраняется.",
                    scheduled_at=now,
                    next_attempt_at=now,
                )
            )
            db.flush()
    except IntegrityError:
        pass


def _downgrade_to_free(subscription: UserSubscription) -> None:
    subscription.plan_code = "free"
    subscription.billing_interval = None
    subscription.status = "free"
    subscription.current_period_start = None
    subscription.current_period_end = None
    subscription.cancel_at_period_end = False
    subscription.scheduled_plan_code = None
    subscription.scheduled_billing_interval = None
    subscription.yookassa_payment_method_id = None
    subscription.retry_count = 0
    subscription.next_retry_at = None


def _record_renewal_failure(
    db: Session, subscription: UserSubscription, payment: BillingPayment, code: str, now: datetime
) -> None:
    subscription.status = "past_due"
    subscription.retry_count += 1
    payment.failure_code = code[:80]
    payment.status = "retry" if payment.provider_payment_id is None else "canceled"
    delays = settings.subscription_retry_delay_list
    if subscription.retry_count <= len(delays):
        subscription.next_retry_at = now + timedelta(hours=delays[subscription.retry_count - 1])
    else:
        grace_end = (subscription.current_period_end or now) + timedelta(
            days=settings.subscription_grace_period_days
        )
        if now < grace_end:
            subscription.next_retry_at = grace_end
        else:
            _downgrade_to_free(subscription)
    _enqueue_payment_issue(db, subscription, now)
    db.commit()


def _renewal_payment(db: Session, subscription: UserSubscription) -> BillingPayment:
    period_start = subscription.current_period_end
    if period_start is None:
        raise ValueError("Subscription has no period end")
    existing = db.scalar(
        select(BillingPayment).where(
            BillingPayment.subscription_id == subscription.id,
            BillingPayment.kind == "renewal",
            BillingPayment.period_start == period_start,
        )
    )
    if existing is not None:
        return existing
    target_code = subscription.scheduled_plan_code or subscription.plan_code
    target_interval = subscription.scheduled_billing_interval or subscription.billing_interval
    if target_interval not in BILLING_INTERVALS:
        raise ValueError("Subscription has no paid billing interval")
    plan = get_plan(target_code, require_available=False)
    try:
        with db.begin_nested():
            payment = BillingPayment(
                user_id=subscription.user_id,
                subscription_id=subscription.id,
                idempotence_key=f"new:{uuid4().hex}",
                kind="renewal",
                plan_code=plan.code,
                plan_name=plan.name,
                billing_interval=target_interval,
                amount=plan.price(target_interval),
                currency=settings.yookassa_currency,
                status="created",
                description=f"Продление Axel One {plan.name}, {target_interval}",
                period_start=period_start,
                period_end=add_billing_period(period_start, target_interval),
            )
            db.add(payment)
            db.flush()
            payment.idempotence_key = f"renewal:{subscription.id}:{period_start.date().isoformat()}"
            db.flush()
    except IntegrityError:
        payment = db.scalar(
            select(BillingPayment).where(
                BillingPayment.subscription_id == subscription.id,
                BillingPayment.kind == "renewal",
                BillingPayment.period_start == period_start,
            )
        )
        if payment is None:
            raise
    db.commit()
    return payment


def process_due_subscription(db: Session, subscription_id: int, client: BillingClient) -> bool:
    now = utc_now()
    subscription = db.get(UserSubscription, subscription_id)
    if subscription is None or subscription.plan_code == "free" or not subscription.current_period_end:
        return False
    if subscription.current_period_end > now:
        return False
    if subscription.cancel_at_period_end:
        _downgrade_to_free(subscription)
        db.commit()
        return True
    if not subscription.yookassa_payment_method_id:
        placeholder = _renewal_payment(db, subscription)
        _record_renewal_failure(db, subscription, placeholder, "payment_method_missing", now)
        return True
    if subscription.next_retry_at and subscription.next_retry_at > now:
        return False
    if subscription.retry_count > len(settings.subscription_retry_delay_list):
        _downgrade_to_free(subscription)
        db.commit()
        return True

    payment = _renewal_payment(db, subscription)
    if payment.status == "succeeded":
        return False
    if payment.status == "pending" and payment.provider_payment_id:
        try:
            provider = client.get_payment(payment.provider_payment_id)
            _verify_provider_payment(payment, provider)
        except BillingProviderError:
            return False
        if provider.status == "succeeded" and provider.paid:
            _apply_succeeded(db, payment, provider, now)
            db.commit()
            return True
        if provider.status == "canceled":
            _apply_canceled(payment, provider, now)
            _record_renewal_failure(
                db, subscription, payment, provider.cancellation_reason or "provider_canceled", now
            )
            return True
        return False
    if payment.status == "canceled":
        _record_renewal_failure(db, subscription, payment, payment.failure_code or "provider_canceled", now)
        return True

    claimed = db.execute(
        update(BillingPayment)
        .where(BillingPayment.id == payment.id, BillingPayment.status.in_(["created", "retry"]))
        .values(status="processing", updated_at=now)
    )
    db.commit()
    if not claimed.rowcount:
        return False
    db.refresh(payment)
    user = db.get(User, subscription.user_id)
    if user is None:
        return False
    try:
        provider = client.create_recurring_payment(
            _provider_payload(payment, user, recurring=True), payment.idempotence_key
        )
        _verify_provider_payment(payment, provider)
    except BillingProviderError as exc:
        _record_renewal_failure(db, subscription, payment, exc.code, now)
        return True
    except WebhookVerificationError:
        _record_renewal_failure(db, subscription, payment, "provider_response_mismatch", now)
        return True
    payment.provider_payment_id = provider.id
    if provider.status == "succeeded" and provider.paid:
        _apply_succeeded(db, payment, provider, now)
    elif provider.status == "canceled":
        _apply_canceled(payment, provider, now)
        _record_renewal_failure(
            db, subscription, payment, provider.cancellation_reason or "provider_canceled", now
        )
        return True
    else:
        payment.status = "pending"
        subscription.status = "past_due"
    db.commit()
    return True


def due_subscription_ids(db: Session) -> list[int]:
    now = utc_now()
    return list(
        db.scalars(
            select(UserSubscription.id)
            .where(
                UserSubscription.plan_code != "free",
                UserSubscription.status.in_(["active", "past_due", "cancel_scheduled"]),
                UserSubscription.current_period_end <= now,
                (UserSubscription.next_retry_at.is_(None) | (UserSubscription.next_retry_at <= now)),
            )
            .order_by(UserSubscription.current_period_end, UserSubscription.id)
            .limit(settings.subscription_worker_batch_size)
        ).all()
    )
