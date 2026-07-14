"""LLM 제공자 추상화.

slides + transcript + personas를 바탕으로 예상 질문·꼬리질문을 생성하는 인터페이스.
출력은 questions 테이블(persona·strategy·evidence)과 1:1 매핑되는 QuestionDraft.
세부 계약: docs/ai-pipeline/qna-prompt-workflow.md
"""

from abc import ABC, abstractmethod
from collections import defaultdict

from app.db.enums import QuestionerPersona, QuestionStrategy
from app.schemas.qna import QuestionDraft
from app.schemas.report import ReportDraft

# A11 · DDL CHECK(follow_up_depth IN (0,1)): 1차 질문(0)에만 꼬리질문(1) 1개.
MAX_FOLLOW_UP_DEPTH = 1


def build_type_scores(
    pairs: list[tuple[QuestionStrategy, float]],
) -> dict[QuestionStrategy, float]:
    """(전략, 답변별 점수) 쌍들을 전략별 평균(0~1, 소수 2자리)으로 집계한다.

    한 전략에 답변이 여러 개면 평균. 답변 0개인 전략 키는 생략(등장 전략만, api-spec §5.2).
    **숫자 집계는 코드 몫** — LLM엔 답변별 점수만 시키고 여기서 평균한다(숫자 계산 금지 원칙).
    두 제공자(gemini·mock)가 공유하므로 base에 둔다.
    """
    buckets: dict[QuestionStrategy, list[float]] = defaultdict(list)
    for strategy, score in pairs:
        buckets[strategy].append(max(0.0, min(1.0, float(score))))
    return {s: round(sum(v) / len(v), 2) for s, v in buckets.items()}


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
        persona: QuestionerPersona,
    ) -> QuestionDraft | None:
        """직전 답변에 대한 꼬리질문. depth≥1이면 항상 None(A11), 불필요해도 None.

        persona: 부모 질문의 페르소나. 꼬리질문은 부모의 페르소나·말투를 그대로 승계한다.
        """
        raise NotImplementedError

    @abstractmethod
    async def generate_report(
        self,
        *,
        answers: list[dict],
        speech_name: str | None = None,
    ) -> ReportDraft:
        """Q&A 로그를 채점해 리포트 정성 평가(type_scores·insight)를 만든다(§B).

        answers: 답변별 `{"strategy", "question", "answer"}` 목록.
          strategy는 질문 생성 때 배정된 QuestionStrategy(채점 축), answer는 raw STT 원문.
        전략별 집계는 build_type_scores로 코드에서 처리 — LLM엔 답변별 점수만 시킨다.
        WPM·필러 등 숫자는 여기서 다루지 않는다(services/report.py §A 몫).
        """
        raise NotImplementedError
