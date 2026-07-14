"""Gemini 제공자 — LLMProvider의 실제 구현.

google-genai SDK를 사용한다. AI Studio 키("AIza…")와 Vertex AI express
mode 키("AQ.…") 모두 지원하며, 키 접두사로 엔드포인트를 자동 선택한다.
출력은 response_schema로 JSON을 강제하고, persona·evidence는 코드에서 사후검증한다.
세부 계약·격차: docs/ai-pipeline/qna-prompt-workflow.md

토큰 절약(implicit caching): Gemini 2.5는 요청 앞쪽의 '공통 프리픽스'를 자동으로
캐시해 반복 호출 시 그만큼을 캐시 단가로 청구한다(2.5 Flash/Pro 최소 2048토큰,
공통 콘텐츠를 앞에 둘수록 적중률↑). 그래서 세션과 무관하게 고정인 역할·페르소나
사전·전략 가이드·규칙은 전부 하나의 system_instruction(_SYSTEM_INSTRUCTION)으로
모아 generate_questions·follow_up 두 경로가 똑같이 재사용한다. 매 호출 바뀌는
값(제목·슬라이드·전사·질문·답변)만 contents로 보낸다. (꼬리질문 프롬프트는 대개
2048토큰 미만이라 단독으론 캐시 문턱을 못 넘지만, 질문 생성 프롬프트와 프리픽스를
공유해 같은 세션 연속 호출에서 재사용된다.)
"""

import json
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.db.enums import QuestionerPersona, QuestionStrategy
from app.schemas.qna import Evidence, QuestionDraft
from app.schemas.report import ReportDraft
from app.services.llm.base import MAX_FOLLOW_UP_DEPTH, LLMProvider, build_type_scores

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

# 프롬프트에 넣는 텍스트 상한(대략 토큰 폭주 방지용).
_SLIDES_CHAR_LIMIT = 15_000
_TRANSCRIPT_CHAR_LIMIT = 15_000

_PERSONA_STYLE: dict[QuestionerPersona, str] = {
    QuestionerPersona.egen: "부드럽고 공감형. 맥락·배경·발표자의 의도를 궁금해하며 묻는다.",
    QuestionerPersona.teto: "직설적이고 도전적. 논리 허점과 근거 부족을 정면으로 추궁한다.",
    QuestionerPersona.kkondae: "권위적인 연장자. 자기 경험에 빗대어 실무 디테일과 기본기를 확인한다.",
    QuestionerPersona.mungcheong: "잘 이해 못한 듯 되묻는다. 어려운 대목을 더 쉽게 풀어달라고 요청한다.",
    QuestionerPersona.jammin: "건방지게 아는 척하며 반박조로 짧고 도발적으로 지적한다.",
}

_STRATEGY_GUIDE: dict[QuestionStrategy, str] = {
    QuestionStrategy.detail_probe: "세부·구현·측정 환경 등 구체를 파고든다.",
    QuestionStrategy.big_picture: "전체 맥락·의의·차별점 등 큰 그림을 묻는다.",
    QuestionStrategy.basic_concept: "기초 개념 이해를 확인한다.",
    QuestionStrategy.numeric_verification: "제시된 수치·근거의 타당성을 검증한다.",
}

# 답변 채점 기준(§B) — "이 전략 질문에 좋은 답변이란 무엇인가".
_SCORING_RUBRIC: dict[QuestionStrategy, str] = {
    QuestionStrategy.detail_probe: "구체적 근거·사례·구현 디테일이 충분한가.",
    QuestionStrategy.big_picture: "맥락·의의·차별점을 설득력 있게 연결하는가.",
    QuestionStrategy.basic_concept: "기초 개념을 정확히 이해하고 설명하는가.",
    QuestionStrategy.numeric_verification: "수치·근거의 타당성을 검증·설명하는가.",
}


def _build_system_instruction() -> str:
    """generate_questions·follow_up 공용 안정 프리픽스(캐시 대상).

    페르소나 5종·전략 4종·규칙은 세션과 무관하게 고정이라 import 시 1회만 만든다.
    변하는 값(세션 페르소나 목록·자료·답변)은 여기 넣지 않고 contents로 보낸다.
    """
    persona_lines = "\n".join(f"- {p.value}: {_PERSONA_STYLE[p]}" for p in QuestionerPersona)
    strategy_lines = "\n".join(f"- {s.value}: {_STRATEGY_GUIDE[s]}" for s in QuestionStrategy)
    rubric_lines = "\n".join(f"- {s.value}: {_SCORING_RUBRIC[s]}" for s in QuestionStrategy)
    return (
        "당신은 발표 리허설 서비스의 질문 생성·답변 평가 도우미입니다. 항상 한국어로 답합니다.\n\n"
        f"[질문자 페르소나 5종]\n{persona_lines}\n\n"
        f"[질문 전략 4종 — 각 질문에 하나씩 배정]\n{strategy_lines}\n\n"
        "[공통 규칙]\n"
        "- persona는 호출마다 지정되는 목록 값 중 하나만 쓰고, 그 페르소나의 말투를 반영한다.\n"
        "- strategy는 위 4종 중 질문 의도에 가장 맞는 하나를 고른다.\n"
        "- 출력은 지정된 JSON 스키마만 채운다. 스키마 밖 필드나 설명 문장을 덧붙이지 않는다.\n\n"
        "[꼬리질문 규칙]\n"
        "- 발표자 답변은 STT 원문이라 간투사(어·음)·비문이 섞여 있어도 내용으로만 판단한다.\n"
        "- 답변이 충분히 구체적이면 억지로 꼬리질문을 만들지 않는다(needed=false).\n"
        "- 근거·수치·설명이 빈약한 지점이 있을 때만, 바로 그 지점을 파고드는 꼬리질문 1개를 만든다(needed=true).\n\n"
        "[답변 채점 루브릭 — 각 답변을 배정된 전략 기준 0.0~1.0]\n"
        f"{rubric_lines}\n"
        "- 답변이 STT 원문이라 간투사·비문이 있어도 내용으로만 평가한다.\n"
        "- 0.0=전혀 못함, 0.5=보통, 1.0=매우 우수. scores는 답변과 같은 순서로 채운다.\n"
        "- WPM·필러 수 등 숫자는 계산하거나 지어내지 않는다(정량 지표는 별도 코드 몫).\n"
    )


# import 시 1회 구성 — 모든 Gemini 호출이 이 동일 프리픽스를 공유한다(implicit caching).
_SYSTEM_INSTRUCTION = _build_system_instruction()


# ── LLM 출력 스키마(중간형) — 검증 전 원본 ──────────────────────────────────


class _QDraft(BaseModel):
    text: str
    persona: QuestionerPersona
    strategy: QuestionStrategy
    slides: list[int]           # 근거 슬라이드 page 번호


class _QuestionsOut(BaseModel):
    questions: list[_QDraft]


class _FollowUpOut(BaseModel):
    needed: bool                       # 꼬리질문이 필요한가
    text: str | None = None
    strategy: QuestionStrategy | None = None


class _AnswerScore(BaseModel):
    score: float                       # 답변 1건 점수 0.0~1.0 (입력 순서대로)


class _ReportOut(BaseModel):
    scores: list[_AnswerScore]         # 답변과 같은 순서
    insight: str                       # 세션 코칭 한두 문장


class GeminiLLMProvider(LLMProvider):
    def __init__(self) -> None:
        key = settings.gemini_api_key
        if not key:
            raise ValueError("GEMINI_API_KEY가 비어 있습니다. backend/.env를 확인하세요.")
        # 엔드포인트는 설정으로 명시(GEMINI_USE_VERTEX). 과거엔 "AQ." 접두사로 Vertex
        # express 키를 판별했지만, AI Studio 무료 키도 AQ. 형식으로 발급되면서
        # 접두사 추정이 무료 키를 결제 필수 경로(aiplatform)로 잘못 보내게 됐다.
        self._client = genai.Client(vertexai=settings.gemini_use_vertex, api_key=key)
        self._model = settings.gemini_model

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
        prompt = self._questions_prompt(speech_name, slides, transcript, pool, count)
        out = await self._generate(prompt, _QuestionsOut, temperature=0.7)

        valid_pages = {s.get("page") for s in (slides or []) if s.get("page") is not None}

        drafts: list[QuestionDraft] = []
        for i, q in enumerate(out.questions[:count]):
            if not q.text.strip():
                continue
            # 모델이 선택 목록 밖 페르소나를 주면 라운드로빈으로 교정(격차 4).
            persona = q.persona if q.persona in pool else pool[len(drafts) % len(pool)]
            drafts.append(QuestionDraft(
                text=q.text.strip(),
                persona=persona,
                strategy=q.strategy,
                evidence=self._clean_evidence(q.slides, valid_pages),
            ))
        return drafts

    async def follow_up(
        self,
        *,
        question: str,
        answer: str,
        depth: int,
    ) -> QuestionDraft | None:
        if depth >= MAX_FOLLOW_UP_DEPTH:  # A11: 1차 질문(0)에만 꼬리질문 1개
            return None
        # 판단 규칙(STT 견딤·needed 분기)은 _SYSTEM_INSTRUCTION에 있고, 여기엔 이번 건만 담는다.
        prompt = (
            "[작업] 꼬리질문 판단\n"
            f"[원 질문] {question}\n"
            f"[발표자 답변] {answer}\n\n"
            "needed=true면 파고들 한국어 꼬리질문 1개(text)와 그에 맞는 strategy를 채우고, "
            "아니면 needed=false로 둔다.\n"
        )
        out = await self._generate(prompt, _FollowUpOut, temperature=0.5)
        if not out.needed or not out.text or not out.text.strip():
            return None
        return QuestionDraft(
            text=out.text.strip(),
            # 부모 persona는 라우터가 승계. 여기선 기본값을 두고 라우터가 덮어쓴다.
            persona=QuestionerPersona.egen,
            strategy=out.strategy or QuestionStrategy.detail_probe,
            follow_up_depth=depth + 1,
        )

    async def generate_report(
        self,
        *,
        answers: list[dict],
        speech_name: str | None = None,
    ) -> ReportDraft:
        # 채점 가능한 답변(전략 유효 + 본문 있음)만 추림 — 순서를 scores와 정렬 기준으로 삼는다.
        scorable: list[tuple[QuestionStrategy, str, str]] = []
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
            scorable.append((strategy, str(a.get("question", "")).strip(), text))
        if not scorable:
            return ReportDraft(type_scores={}, insight="답변이 없어 평가할 내용이 없습니다.")

        prompt = self._report_prompt(scorable, speech_name)
        out = await self._generate(prompt, _ReportOut, temperature=0.3)

        # LLM이 답변 수와 다른 개수를 줄 수 있으니 zip으로 안전 정렬(짧은 쪽 기준).
        pairs = [(strat, sc.score) for (strat, _q, _a), sc in zip(scorable, out.scores)]
        return ReportDraft(
            type_scores=build_type_scores(pairs),
            insight=(out.insight or "").strip(),
        )

    # ── 프롬프트 구성 ───────────────────────────────────────────────────────

    def _report_prompt(
        self, scorable: list[tuple[QuestionStrategy, str, str]], speech_name: str | None,
    ) -> str:
        # 루브릭·규칙은 _SYSTEM_INSTRUCTION(캐시)에 있고, 여기엔 이번 세션 답변만 담는다.
        lines = []
        for i, (strategy, question, answer) in enumerate(scorable, 1):
            lines.append(f"{i}. [전략:{strategy.value}] 질문: {question}\n   답변: {answer}")
        body = "\n".join(lines)
        return (
            "[작업] 답변 채점 + 인사이트\n"
            f"[발표 제목] {speech_name or '(제목 없음)'}\n\n"
            f"[답변 목록 — 각 답변을 배정된 전략 기준으로 0.0~1.0 채점]\n{body}\n\n"
            "scores 배열에 위 번호와 같은 순서로 각 답변의 점수를 채운다.\n"
            "insight에는 발표자에게 도움이 될 한국어 코칭 한두 문장을 쓴다.\n"
        )

    def _questions_prompt(
        self, speech_name: str, slides: list[dict] | None,
        transcript: list[dict] | None, pool: list[QuestionerPersona], count: int,
    ) -> str:
        # 안정 규칙·페르소나/전략 정의는 _SYSTEM_INSTRUCTION에 있고, 여기엔 변하는 값만 담는다.
        persona_pool = ", ".join(p.value for p in pool)
        return (
            "[작업] 예상 질문 생성\n"
            f"아래 발표에 대해 청중이 던질 법한 질문을 정확히 {count}개 만드세요.\n\n"
            f"[이번 세션 페르소나 — 이 목록 안에서만 배정, 고르게 분배] {persona_pool}\n\n"
            f"[발표 제목] {speech_name}\n\n"
            f"[발표 자료(슬라이드)]\n{self._format_slides(slides)}\n\n"
            f"[발표 전사(말한 내용)]\n{self._format_transcript(transcript)}\n\n"
            "규칙:\n"
            "- 슬라이드에 있으나 전사에서 언급되지 않은 지점, 또는 언급했으나 근거·수치가 약한 주장을 우선 겨냥한다.\n"
            "- 질문끼리 관점이 겹치지 않게 한다.\n"
            "- 각 질문의 근거 슬라이드를 slides(페이지 번호 배열)로 표기한다. "
            "근거가 없으면 빈 배열로 둔다. 존재하지 않는 페이지를 지어내지 않는다.\n"
        )

    def _format_slides(self, slides: list[dict] | None) -> str:
        if not slides:
            return "(자료 없음)"
        out, used = [], 0
        for s in slides:
            line = f"[p{s.get('page')}] {str(s.get('text', '')).strip()}"
            used += len(line)
            if used > _SLIDES_CHAR_LIMIT:
                break
            out.append(line)
        return "\n".join(out)

    def _format_transcript(self, transcript: list[dict] | None) -> str:
        # 팀 합의: 외부 LLM에는 타임스탬프 없이 텍스트만 보낸다(타게팅용 맥락).
        # 타임스탬프 포함 원본은 transcripts.segments에 저장돼 리포트 분석에서 쓰인다.
        if not transcript:
            return "(전사 없음)"
        out, used = [], 0
        for seg in transcript:
            line = str(seg.get("text", "")).strip()
            if not line:
                continue
            used += len(line)
            if used > _TRANSCRIPT_CHAR_LIMIT:
                break
            out.append(line)
        return "\n".join(out)

    # ── evidence 사후검증 ───────────────────────────────────────────────────

    @staticmethod
    def _clean_evidence(slides: list[int], valid_pages: set) -> Evidence:
        # 환각 근거 제거: 실제 page 밖은 버린다(질문 텍스트는 유지).
        # transcript_refs는 LLM이 타임스탬프를 못 보므로 생성 단계에선 비운다(팀 합의).
        pages = [p for p in dict.fromkeys(slides) if p in valid_pages]
        return Evidence(slides=pages, transcript_refs=[])

    # ── 공통 생성 ───────────────────────────────────────────────────────────

    async def _generate(
        self, prompt: str, schema: type[_SchemaT], *, temperature: float
    ) -> _SchemaT:
        # system_instruction = 캐시 가능한 공통 프리픽스, contents = 매번 바뀌는 값.
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
            ),
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        # SDK 파싱이 비어 오는 경우(드묾) 텍스트에서 직접 복원.
        return schema.model_validate(json.loads(response.text or ""))
