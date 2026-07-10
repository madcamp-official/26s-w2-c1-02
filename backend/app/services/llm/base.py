"""LLM 제공자 추상화.

발표 자료/청중 유형을 바탕으로 질의응답 질문을 생성하는 인터페이스.
지금은 Mock만 구현. 추후 Gemini 등 실제 제공자를 이 인터페이스로 붙인다.
"""

from abc import ABC, abstractmethod

from app.schemas.common import AudienceType
from app.schemas.qna import QnaItem


class LLMProvider(ABC):
    @abstractmethod
    async def generate_questions(
        self,
        *,
        speech_name: str,
        material_text: str | None,
        audience_type: AudienceType,
        audience_detail: str | None,
        count: int,
    ) -> list[QnaItem]:
        """발표 맥락으로부터 질문 목록을 생성한다."""
        raise NotImplementedError

    @abstractmethod
    async def follow_up(
        self,
        *,
        question: str,
        answer: str,
        depth: int,
    ) -> QnaItem | None:
        """직전 답변에 대한 꼬리물기 질문(최대 3단계). 없으면 None."""
        raise NotImplementedError
