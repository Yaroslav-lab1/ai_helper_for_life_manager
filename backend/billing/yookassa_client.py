from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from threading import Lock
from typing import Any, Protocol

from backend.config import settings

logger = logging.getLogger(__name__)


class BillingProviderError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ProviderPayment:
    id: str
    status: str
    amount: Decimal
    currency: str
    metadata: dict[str, str] = field(default_factory=dict)
    confirmation_url: str | None = None
    payment_method_id: str | None = None
    payment_method_saved: bool = False
    paid: bool = False
    cancellation_reason: str | None = None
    refunded_amount: Decimal = Decimal("0.00")


class BillingClient(Protocol):
    def create_initial_payment(self, payload: dict[str, Any], idempotence_key: str) -> ProviderPayment: ...

    def create_recurring_payment(self, payload: dict[str, Any], idempotence_key: str) -> ProviderPayment: ...

    def get_payment(self, payment_id: str) -> ProviderPayment: ...


def _attr(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _normalize(payment: Any) -> ProviderPayment:
    amount = _attr(payment, "amount")
    confirmation = _attr(payment, "confirmation")
    method = _attr(payment, "payment_method")
    cancellation = _attr(payment, "cancellation_details")
    refunded = _attr(payment, "refunded_amount")
    raw_metadata = _attr(payment, "metadata", {}) or {}
    metadata = {str(key): str(value) for key, value in dict(raw_metadata).items()}
    return ProviderPayment(
        id=str(_attr(payment, "id")),
        status=str(_attr(payment, "status")),
        amount=Decimal(str(_attr(amount, "value"))),
        currency=str(_attr(amount, "currency")),
        metadata=metadata,
        confirmation_url=_attr(confirmation, "confirmation_url"),
        payment_method_id=str(_attr(method, "id")) if _attr(method, "id") else None,
        payment_method_saved=bool(_attr(method, "saved", False)),
        paid=bool(_attr(payment, "paid", False)),
        cancellation_reason=_attr(cancellation, "reason"),
        refunded_amount=Decimal(str(_attr(refunded, "value", "0.00"))),
    )


class YooKassaClient:
    """Small adapter around the official SDK; no SDK objects cross this boundary."""

    _configuration_lock = Lock()

    def __init__(self) -> None:
        if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
            raise BillingProviderError("provider_not_configured")
        # The SDK configuration is process-global. Configure it once under a lock and
        # expose only immutable Axel One settings to request code.
        with self._configuration_lock:
            from yookassa import Configuration

            Configuration.configure(
                settings.yookassa_shop_id,
                settings.yookassa_secret_key,
                timeout=settings.yookassa_request_timeout_seconds,
                max_attempts=1,
            )

    @staticmethod
    def _payment_api():
        """Return the official Payment facade with an actual network timeout.

        YooKassa SDK 3.11 exposes ``Configuration.timeout`` for polling but does
        not pass it to ``requests.Session.request``. This narrow subclass keeps
        SDK validation/response models and adds the required transport timeout.
        """
        from yookassa import Payment
        from yookassa.client import ApiClient
        from yookassa.domain.common import RequestObject

        class TimedApiClient(ApiClient):
            def request(self, method="", path="", query_params=None, headers=None, body=None):
                if isinstance(body, RequestObject):
                    body.validate()
                    body = dict(body)
                prepared = self.prepare_request_headers(headers)
                raw_response = self.execute(body, method, path, query_params, prepared)
                if raw_response.status_code != 200:
                    self._ApiClient__handle_error(raw_response)
                return raw_response.json()

            def execute(self, body, method, path, query_params, request_headers):
                session = self.get_session()
                try:
                    return session.request(
                        method,
                        self.endpoint + path,
                        params=query_params,
                        headers=request_headers,
                        json=body,
                        verify=self.configuration.verify,
                        timeout=settings.yookassa_request_timeout_seconds,
                    )
                finally:
                    session.close()

        class TimedPayment(Payment):
            def __init__(self):
                self.client = TimedApiClient()

        return TimedPayment

    @staticmethod
    def _create(payload: dict[str, Any], idempotence_key: str) -> ProviderPayment:
        try:
            payment_api = YooKassaClient._payment_api()
            return _normalize(payment_api.create(payload, idempotence_key))
        except Exception as exc:
            logger.warning("YooKassa create payment failed (%s)", type(exc).__name__)
            retryable = type(exc).__name__ in {
                "ConnectionError",
                "ReadTimeout",
                "ConnectTimeout",
                "Timeout",
                "HTTPError",
            }
            raise BillingProviderError(type(exc).__name__[:80], retryable=retryable) from exc

    def create_initial_payment(self, payload: dict[str, Any], idempotence_key: str) -> ProviderPayment:
        return self._create(payload, idempotence_key)

    def create_recurring_payment(self, payload: dict[str, Any], idempotence_key: str) -> ProviderPayment:
        return self._create(payload, idempotence_key)

    def get_payment(self, payment_id: str) -> ProviderPayment:
        try:
            payment_api = self._payment_api()
            return _normalize(payment_api.find_one(payment_id))
        except Exception as exc:
            logger.warning("YooKassa payment lookup failed (%s)", type(exc).__name__)
            raise BillingProviderError(type(exc).__name__[:80], retryable=True) from exc


class FakeYooKassaClient:
    """Deterministic in-memory provider used by tests; it never performs HTTP."""

    def __init__(self) -> None:
        self.payments: dict[str, ProviderPayment] = {}
        self.idempotency_results: dict[str, ProviderPayment] = {}
        self.create_calls: list[tuple[str, dict[str, Any], str]] = []
        self.next_payment: ProviderPayment | None = None
        self.error: BillingProviderError | None = None

    def _create(self, kind: str, payload: dict[str, Any], key: str) -> ProviderPayment:
        self.create_calls.append((kind, payload, key))
        if self.error:
            raise self.error
        existing = self.idempotency_results.get(key)
        if existing:
            return existing
        payment = self.next_payment or ProviderPayment(
            id=f"fake-{len(self.payments) + 1}",
            status="pending",
            amount=Decimal(payload["amount"]["value"]),
            currency=payload["amount"]["currency"],
            metadata={str(k): str(v) for k, v in payload.get("metadata", {}).items()},
            confirmation_url="https://yookassa.test/confirm",
        )
        self.payments[payment.id] = payment
        self.idempotency_results[key] = payment
        self.next_payment = None
        return payment

    def create_initial_payment(self, payload: dict[str, Any], idempotence_key: str) -> ProviderPayment:
        return self._create("initial", payload, idempotence_key)

    def create_recurring_payment(self, payload: dict[str, Any], idempotence_key: str) -> ProviderPayment:
        return self._create("renewal", payload, idempotence_key)

    def get_payment(self, payment_id: str) -> ProviderPayment:
        if self.error:
            raise self.error
        try:
            return self.payments[payment_id]
        except KeyError as exc:
            raise BillingProviderError("payment_not_found") from exc


_client_override: BillingClient | None = None
_runtime_client: BillingClient | None = None


def set_billing_client_for_tests(client: BillingClient | None) -> None:
    global _client_override
    _client_override = client


def reset_billing_client() -> None:
    global _runtime_client, _client_override
    _runtime_client = None
    _client_override = None


def get_billing_client() -> BillingClient:
    global _runtime_client
    if _client_override is not None:
        return _client_override
    if _runtime_client is None:
        _runtime_client = YooKassaClient()
    return _runtime_client
