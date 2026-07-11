from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.mock_provider import MockLLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    """설정에 따라 LLM 제공자를 선택한다."""
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider == "gemini":
        # mock 모드에서는 google-genai 미설치여도 돌도록 지연 임포트.
        from app.services.llm.gemini_provider import GeminiLLMProvider

        return GeminiLLMProvider()
    raise ValueError(f"알 수 없는 LLM_PROVIDER: {settings.llm_provider}")
