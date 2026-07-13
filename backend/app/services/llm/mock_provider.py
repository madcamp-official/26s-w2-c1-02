"""Mock 제공자 — 실제 LLM 없이 새 QuestionDraft 계약 형태의 더미 질문을 생성한다.

FE/BE가 GPU·API 키 없이도 §4.4 전체 형태(persona·strategy·evidence)를 받게 유지 (공통 가이드 2).
"""

from app.db.enums import QuestionerPersona, QuestionStrategy
from app.schemas.qna import Evidence, QuestionDraft
from app.services.llm.base import MAX_FOLLOW_UP_DEPTH, LLMProvider

_STRATEGIES = list(QuestionStrategy)


class MockLLMProvider(LLMProvider):
    async def generate_questions(
        self,
        *,
        speech_name: str,
        slides: list[dict] | None,
        transcript: list[dict] | None,
        personas: list[QuestionerPersona],
        count: int,
    ) -> list[QuestionDraft]:
        pool = personas or [QuestionerPersona.egen]
        first_page = (slides[0].get("page") if slides else None)
        drafts: list[QuestionDraft] = []
        for i in range(count):
            drafts.append(QuestionDraft(
                text=f"(예시) '{speech_name}' 발표 관련 질문 {i + 1}입니다. 이 부분을 더 설명해 주시겠어요?",
                persona=pool[i % len(pool)],                 # 선택 목록 라운드로빈
                strategy=_STRATEGIES[i % len(_STRATEGIES)],  # 전략 순환
                # transcript_refs는 생성 단계에서 비운다(외부 LLM에 타임스탬프 미전달).
                evidence=Evidence(slides=[first_page] if first_page is not None else []),
            ))
        return drafts

    async def follow_up(
        self,
        *,
        question: str,
        answer: str,
        depth: int,
    ) -> QuestionDraft | None:
        if depth >= MAX_FOLLOW_UP_DEPTH:
            return None
        return QuestionDraft(
            text="(예시) 방금 답변에 대해 조금 더 구체적으로 말씀해 주시겠어요?",
            persona=QuestionerPersona.egen,
            strategy=QuestionStrategy.detail_probe,
            follow_up_depth=depth + 1,
        )
