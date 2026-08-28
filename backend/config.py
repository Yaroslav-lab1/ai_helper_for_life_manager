from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    app_name: str = "Axel One API"
    environment: str = "development"
    database_url: str = "sqlite:///./axel.db"
    secret_key: str = "change-me-in-production"
    access_token_minutes: int = 30
    refresh_token_days: int = 30
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    llm_provider: str = "ollama"
    llm_model: str = "qwen3.5:9b"
    ollama_base_url: str = "http://localhost:11434"
    ollama_request_timeout_seconds: int = 120
    gigachat_authorization_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_base_url: str = "https://api.giga.chat/v1"
    gigachat_oauth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_request_timeout_seconds: int = 120
    gigachat_verify_ssl: bool = True
    gigachat_ca_bundle_file: str = str(
        Path(__file__).resolve().parent / "certs" / "russian_trusted_root_ca.pem"
    )
    ai_max_message_chars: int = 4000
    ai_max_context_chars: int = 16000
    ai_max_concurrent_generations: int = 2
    domain: str = ""
    trusted_hosts: str = "localhost,127.0.0.1,testserver"
    trusted_proxies: str = "127.0.0.1,::1"
    enable_demo_seed: bool = False
    demo_email: str = "demo@axel.one"
    demo_password: str = ""
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 300
    auth_rate_limit_attempts: int = 8
    auth_rate_limit_window_seconds: int = 900
    email_backend: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_from: str = ""
    email_token_minutes: int = 30
    privacy_policy_version: str = "2026-08-17"
    use_secure_auth_cookies: bool = False
    refresh_cookie_name: str = "axel_refresh"
    refresh_cookie_samesite: str = "lax"
    notification_worker_enabled: bool = False
    notification_poll_interval_seconds: int = 30
    notification_schedule_horizon_hours: int = 48
    notification_retry_base_seconds: int = 60
    notification_retry_max_seconds: int = 3600
    notification_max_attempts: int = 5
    notification_claim_timeout_seconds: int = 300
    notification_batch_size: int = 20
    yookassa_enabled: bool = False
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    yookassa_return_url: str = "https://example.com/billing/return"
    yookassa_currency: str = "RUB"
    yookassa_capture: bool = True
    yookassa_recurring_payments_enabled: bool = False
    yookassa_webhook_ip_check_enabled: bool = True
    yookassa_request_timeout_seconds: int = 30
    yookassa_receipt_mode: str = "disabled"
    yookassa_vat_code: str = ""
    yookassa_tax_system_code: str = ""
    yookassa_payment_subject: str = "service"
    yookassa_payment_mode: str = "full_payment"
    subscription_grace_period_days: int = 3
    subscription_retry_delays_hours: str = "24,72"
    subscription_worker_poll_interval_seconds: int = 300
    subscription_worker_batch_size: int = 20
    executive_plan_enabled: bool = True

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def trusted_host_list(self) -> list[str]:
        return [item.strip() for item in self.trusted_hosts.split(",") if item.strip()]

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def public_base_url(self) -> str:
        return f"https://{self.domain}" if self.domain else "http://localhost:5173"

    @property
    def subscription_retry_delay_list(self) -> list[int]:
        try:
            values = [int(item.strip()) for item in self.subscription_retry_delays_hours.split(",") if item.strip()]
        except ValueError as exc:
            raise RuntimeError("SUBSCRIPTION_RETRY_DELAYS_HOURS must be comma-separated positive integers") from exc
        if not values or any(value <= 0 for value in values) or values != sorted(set(values)):
            raise RuntimeError("SUBSCRIPTION_RETRY_DELAYS_HOURS must contain increasing unique positive integers")
        return values

    def _validate_billing(self, errors: list[str]) -> None:
        receipt_modes = {"self_employed", "54fz", "external", "disabled"}
        if self.yookassa_receipt_mode not in receipt_modes:
            errors.append("YOOKASSA_RECEIPT_MODE must be self_employed, 54fz, external or disabled")
        if self.yookassa_currency != "RUB":
            errors.append("YOOKASSA_CURRENCY must be RUB for the configured tariff catalog")
        if not self.yookassa_capture:
            errors.append("YOOKASSA_CAPTURE must be true because Axel One uses one-stage payments")
        if self.yookassa_request_timeout_seconds < 1:
            errors.append("YOOKASSA_REQUEST_TIMEOUT_SECONDS must be positive")
        if self.subscription_grace_period_days < 0:
            errors.append("SUBSCRIPTION_GRACE_PERIOD_DAYS cannot be negative")
        if self.subscription_worker_poll_interval_seconds < 1 or self.subscription_worker_batch_size < 1:
            errors.append("subscription worker interval and batch size must be positive")
        try:
            self.subscription_retry_delay_list
        except RuntimeError as exc:
            errors.append(str(exc))
        if self.yookassa_receipt_mode == "54fz":
            if not self.yookassa_vat_code.isdigit() or not self.yookassa_tax_system_code.isdigit():
                errors.append("54fz receipt mode requires YOOKASSA_VAT_CODE and YOOKASSA_TAX_SYSTEM_CODE")
        if self.yookassa_receipt_mode == "self_employed":
            errors.append(
                "YOOKASSA_RECEIPT_MODE=self_employed is unavailable: YooKassa discontinued its "
                "self-employed receipt service on 2025-12-29; configure external, 54fz or disabled"
            )
        if not self.yookassa_enabled:
            return
        if not self.yookassa_shop_id or not self.yookassa_secret_key:
            errors.append("YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY are required when YOOKASSA_ENABLED=true")
        parsed_return = urlparse(self.yookassa_return_url)
        if self.is_production and parsed_return.scheme != "https":
            errors.append("YOOKASSA_RETURN_URL must use HTTPS in production")
        if self.is_production:
            lowered = self.yookassa_secret_key.lower()
            if lowered.startswith("test_") or "replace" in lowered or "changeme" in lowered:
                errors.append("production requires a non-test YOOKASSA_SECRET_KEY")
            if self.yookassa_shop_id.lower() in {"test", "example", "changeme"}:
                errors.append("production requires a real YOOKASSA_SHOP_ID")

    def validate_runtime(self) -> None:
        errors: list[str] = []
        self._validate_billing(errors)
        if not self.is_production:
            if errors:
                raise RuntimeError("Invalid billing configuration:\n- " + "\n- ".join(errors))
            return
        weak_secrets = {
            "change-me-in-production",
            "local-development-key-change-in-production",
            "test-key-only",
            "secret",
            "development-only-secret-key-not-for-production",
            "development-only-change-before-production",
        }
        if len(self.secret_key) < 32 or self.secret_key.lower() in weak_secrets:
            errors.append("SECRET_KEY must be a unique random value of at least 32 characters")
        try:
            database = make_url(self.database_url)
            if not database.drivername.startswith("postgresql"):
                errors.append("DATABASE_URL must use PostgreSQL in production")
            password = database.password or ""
            if not password or password.lower() in {
                "axel",
                "postgres",
                "password",
                "changeme",
                "change-me",
                "development-only-db-password",
                "replace-with-a-unique-random-database-password",
            }:
                errors.append("DATABASE_URL must contain a non-default PostgreSQL password")
        except Exception:
            errors.append("DATABASE_URL is invalid")
        if self.enable_demo_seed:
            errors.append("ENABLE_DEMO_SEED cannot be enabled in production")
        if not self.domain:
            errors.append("DOMAIN is required in production")
        if any(origin == "*" or "localhost" in origin for origin in self.cors_origin_list):
            errors.append("CORS_ORIGINS must contain only explicit production HTTPS origins")
        elif not self.cors_origin_list or any(not origin.startswith("https://") for origin in self.cors_origin_list):
            errors.append("CORS_ORIGINS must use HTTPS in production")
        if "*" in self.trusted_host_list or self.domain not in self.trusted_host_list:
            errors.append("TRUSTED_HOSTS must explicitly include DOMAIN and cannot use a wildcard")
        if self.email_backend != "smtp" or not self.smtp_host or not self.email_from:
            errors.append("production email requires EMAIL_BACKEND=smtp, SMTP_HOST and EMAIL_FROM")
        if self.email_backend == "smtp" and self.smtp_username and not self.smtp_password:
            errors.append("SMTP_PASSWORD is required when SMTP_USERNAME is configured")
        if not self.use_secure_auth_cookies:
            errors.append("USE_SECURE_AUTH_COOKIES must be true in production")
        if self.refresh_cookie_samesite not in {"lax", "strict"}:
            errors.append("REFRESH_COOKIE_SAMESITE must be lax or strict in production")
        if self.llm_provider == "gigachat" and not self.gigachat_authorization_key:
            errors.append("GIGACHAT_AUTHORIZATION_KEY is required for the GigaChat provider")
        if not self.notification_worker_enabled:
            errors.append("NOTIFICATION_WORKER_ENABLED must be true in production")
        if self.notification_poll_interval_seconds < 1:
            errors.append("NOTIFICATION_POLL_INTERVAL_SECONDS must be positive")
        if self.notification_schedule_horizon_hours < 1:
            errors.append("NOTIFICATION_SCHEDULE_HORIZON_HOURS must be positive")
        if self.notification_retry_base_seconds < 1:
            errors.append("NOTIFICATION_RETRY_BASE_SECONDS must be positive")
        if self.notification_retry_max_seconds < self.notification_retry_base_seconds:
            errors.append("NOTIFICATION_RETRY_MAX_SECONDS cannot be below the retry base")
        if self.notification_max_attempts < 1:
            errors.append("NOTIFICATION_MAX_ATTEMPTS must be positive")
        if self.notification_claim_timeout_seconds < 1:
            errors.append("NOTIFICATION_CLAIM_TIMEOUT_SECONDS must be positive")
        if self.notification_batch_size < 1:
            errors.append("NOTIFICATION_BATCH_SIZE must be positive")
        if errors:
            raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
