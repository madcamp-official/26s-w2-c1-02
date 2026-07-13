"""Mock 제공자 — 실제 LLM 없이 새 QuestionDraft 계약 형태의 더미 질문을 생성한다.

FE/BE가 GPU·API 키 없이도 §4.4 전체 형태(persona·strategy·evidence)를 받게 유지 (공통 가이드 2).
"""

from app.db.enums import QuestionerPersona, QuestionStrategy
from app.schemas.qna import Evidence, QuestionDraft
from app.schemas.report import ReportDraft
from app.services.llm.base import MAX_FOLLOW_UP_DEPTH, LLMProvider, build_type_scores

_STRATEGIES = list(QuestionStrategy)


def _mock_score(answer: str) -> float:
    """답변 길이에 비례한 결정론적 점수(0.3~0.9). 실제 채점 아님 — 오프라인 CI 고정값용."""
    return round(min(0.9, 0.3 + len(answer.strip()) / 200), 2)


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

    async def generate_report(
        self,
        *,
        answers: list[dict],
        speech_name: str | None = None,
    ) -> ReportDraft:
        pairs: list[tuple[QuestionStrategy, float]] = []
        for a in answers:
            text = str(a.get("answer", "")).strip()
            if not text:
                continue
            strategy = a.get("strategy")
            if not isinstance(strategy, QuestionStrategy):
                try:
                    strategy = QuestionStrategy(str(strategy))
                except ValueError:
                    continue
            pairs.append((strategy, _mock_score(text)))
        type_scores = build_type_scores(pairs)
        insight = (
            "(예시) 전반적으로 무난한 답변이에요. 근거 수치를 한두 개 덧붙이면 설득력이 올라갑니다."
            if type_scores
            else "(예시) 채점할 답변이 없습니다."
        )
        return ReportDraft(type_scores=type_scores, insight=insight)
