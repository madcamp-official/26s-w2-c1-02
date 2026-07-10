from app.schemas.common import AudienceType
from app.schemas.qna import QnaItem
from app.services.llm.base import LLMProvider

_MAX_FOLLOW_UP_DEPTH = 3


class MockLLMProvider(LLMProvider):
    """실제 LLM 없이 더미 질문을 생성한다."""

    async def generate_questions(
        self,
        *,
        speech_name: str,
        material_text: str | None,
        audience_type: AudienceType,
        audience_detail: str | None,
        count: int,
    ) -> list[QnaItem]:
        return [
            QnaItem(
                index=i + 1,
                question=(
                    f"(예시) '{speech_name}' 발표 내용 관련 질문 {i + 1}입니다. "
                    "이 부분을 더 설명해 주시겠어요?"
                ),
            )
            for i in range(count)
        ]

    async def follow_up(
        self,
        *,
        question: str,
        answer: str,
        depth: int,
    ) -> QnaItem | None:
        if depth >= _MAX_FOLLOW_UP_DEPTH:
            return None
        return QnaItem(
            index=0,
            question="(예시) 방금 답변에 대해 조금 더 구체적으로 말씀해 주시겠어요?",
            follow_up_depth=depth + 1,
        )
