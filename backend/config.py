from functools import lru_cache
from pathlib import Path

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
    privacy_policy_version: str = "2026-07-28"
    use_secure_auth_cookies: bool = False
    refresh_cookie_name: str = "axel_refresh"
    refresh_cookie_samesite: str = "lax"

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

    def validate_runtime(self) -> None:
        if not self.is_production:
            return
        errors: list[str] = []
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
        if errors:
            raise RuntimeError("Unsafe production configuration:\n- " + "\n- ".join(errors))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
