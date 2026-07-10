from functools import lru_cache

from app.core.config import settings
from app.services.llm.base import LLMProvider
from app.services.llm.mock_provider import MockLLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    """설정에 따라 LLM 제공자를 선택한다.

    지금은 mock만 구현. 'gemini' 선택 시 GeminiProvider를 붙이면 된다.
    (예: app/services/llm/gemini_provider.py 를 만들고 여기서 분기)
    """
    provider = settings.llm_provider.lower()
    if provider == "mock":
        return MockLLMProvider()
    if provider == "gemini":
        # TODO: GeminiProvider 구현 후 연결.
        raise NotImplementedError(
            "Gemini 제공자는 아직 구현되지 않았습니다. LLM_PROVIDER=mock 을 사용하세요."
        )
    raise ValueError(f"알 수 없는 LLM_PROVIDER: {settings.llm_provider}")
