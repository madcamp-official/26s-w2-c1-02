"""LLM 제공자 추상화.

slides + transcript + personas를 바탕으로 예상 질문·꼬리질문을 생성하는 인터페이스.
출력은 questions 테이블(persona·strategy·evidence)과 1:1 매핑되는 QuestionDraft.
세부 계약: docs/ai-pipeline/qna-prompt-workflow.md
"""

from abc import ABC, abstractmethod

from app.db.enums import QuestionerPersona
from app.schemas.qna import QuestionDraft

# A11 · DDL CHECK(follow_up_depth IN (0,1)): 1차 질문(0)에만 꼬리질문(1) 1개.
MAX_FOLLOW_UP_DEPTH = 1


class LLMProvider(ABC):
    @abstractmethod
    async def generate_questions(
        self,
        *,
        speech_name: str,
        slides: list[dict] | None,
        transcript: list[dict] | None,
        personas: list[QuestionerPersona],
        count: int,
    ) -> list[QuestionDraft]:
        """slides(자료)와 transcript(발표 전사)를 대조해 예상 질문을 생성한다.

        slides: [{"page":1,"text":"..."}] · transcript: [{"start","end","text"}] (둘 다 없을 수 있음).
        personas: 세션이 고른 질문자 페르소나(≥1). 질문마다 이 목록 안에서 배정된다.
        """
        raise NotImplementedError

    @abstractmethod
    async def follow_up(
        self,
        *,
        question: str,
        answer: str,
        depth: int,
    ) -> QuestionDraft | None:
        """직전 답변에 대한 꼬리질문. depth≥1이면 항상 None(A11), 불필요해도 None."""
        raise NotImplementedError
