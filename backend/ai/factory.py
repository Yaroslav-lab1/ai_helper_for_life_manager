from functools import lru_cache

from backend.ai.client import GigaChatLLMClient, LLMClient, MockLLMClient, OllamaLLMClient
from backend.config import get_settings


def create_llm_client() -> LLMClient:
    settings = get_settings()
    provider = settings.llm_provider.strip().lower()
    if provider == "mock":
        return MockLLMClient()
    if provider == "ollama":
        return OllamaLLMClient(
            model=settings.llm_model,
            base_url=settings.ollama_base_url,
            timeout_seconds=settings.ollama_request_timeout_seconds,
        )
    if provider == "gigachat":
        return GigaChatLLMClient(
            model=settings.llm_model,
            authorization_key=settings.gigachat_authorization_key,
            scope=settings.gigachat_scope,
            base_url=settings.gigachat_base_url,
            oauth_url=settings.gigachat_oauth_url,
            timeout_seconds=settings.gigachat_request_timeout_seconds,
            verify_ssl=settings.gigachat_verify_ssl,
            ca_bundle_file=settings.gigachat_ca_bundle_file,
        )
    raise ValueError(f"Неподдерживаемый LLM_PROVIDER: {settings.llm_provider}")


@lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    """Reuse one client so GigaChat OAuth tokens are cached between API requests."""
    return create_llm_client()
