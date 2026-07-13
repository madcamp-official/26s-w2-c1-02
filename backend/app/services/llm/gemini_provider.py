"""Gemini 제공자 — LLMProvider의 실제 구현.

google-genai SDK를 사용한다. AI Studio 키("AIza…")와 Vertex AI express
mode 키("AQ.…") 모두 지원하며, 키 접두사로 엔드포인트를 자동 선택한다.
출력은 response_schema로 JSON을 강제하고, persona·evidence는 코드에서 사후검증한다.
세부 계약·격차: docs/ai-pipeline/qna-prompt-workflow.md
"""

import json
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.db.enums import QuestionerPersona, QuestionStrategy
from app.schemas.qna import Evidence, QuestionDraft, TranscriptRef
from app.services.llm.base import MAX_FOLLOW_UP_DEPTH, LLMProvider

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


def _mmss(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 60:02d}:{s % 60:02d}"


# ── LLM 출력 스키마(중간형) — 검증 전 원본 ──────────────────────────────────


class _QDraft(BaseModel):
    text: str
    persona: QuestionerPersona
    strategy: QuestionStrategy
    slides: list[int]           # 근거 슬라이드 page 번호
    transcript_starts: list[float]  # 근거 전사 구간 시작(초)


class _QuestionsOut(BaseModel):
    questions: list[_QDraft]


class _FollowUpOut(BaseModel):
    needed: bool                       # 꼬리질문이 필요한가
    text: str | None = None
    strategy: QuestionStrategy | None = None


class GeminiLLMProvider(LLMProvider):
    def __init__(self) -> None:
        key = settings.gemini_api_key
        if not key:
            raise ValueError("GEMINI_API_KEY가 비어 있습니다. backend/.env를 확인하세요.")
        # "AQ." 접두 = Vertex AI express mode 키 → vertexai 엔드포인트 필요.
        self._client = genai.Client(vertexai=key.startswith("AQ."), api_key=key)
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
        t_range = self._transcript_range(transcript)

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
                evidence=self._clean_evidence(q.slides, q.transcript_starts, valid_pages, t_range),
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
        prompt = (
            "발표 질의응답에서 발표자의 답변을 보고 꼬리질문이 필요한지 판단하세요.\n\n"
            f"[원 질문] {question}\n"
            f"[발표자 답변] {answer}\n\n"
            "답변은 STT 원문이라 간투사(어, 음)·비문이 섞여 있어도 내용으로만 판단하세요.\n"
            "답변이 충분히 구체적이면 needed=false로 두세요.\n"
            "근거·수치·설명이 빈약하면 needed=true로 두고, 그 지점을 파고드는 한국어 꼬리질문 1개와 "
            "그에 맞는 strategy를 채우세요.\n"
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

    # ── 프롬프트 구성 ───────────────────────────────────────────────────────

    def _questions_prompt(
        self, speech_name: str, slides: list[dict] | None,
        transcript: list[dict] | None, pool: list[QuestionerPersona], count: int,
    ) -> str:
        persona_lines = "\n".join(f"- {p.value}: {_PERSONA_STYLE[p]}" for p in pool)
        strategy_lines = "\n".join(f"- {s.value}: {_STRATEGY_GUIDE[s]}" for s in QuestionStrategy)
        return (
            "당신은 발표 리허설 서비스의 예상 질문 생성기입니다.\n"
            f"아래 발표에 대해 청중이 던질 법한 질문을 정확히 {count}개, 한국어로 만드세요.\n\n"
            f"[발표 제목] {speech_name}\n\n"
            f"[질문자 페르소나 — 이 목록 안에서만 배정, 고르게 분배]\n{persona_lines}\n\n"
            f"[질문 전략 — 각 질문에 하나]\n{strategy_lines}\n\n"
            f"[발표 자료(슬라이드)]\n{self._format_slides(slides)}\n\n"
            f"[발표 전사(말한 내용)]\n{self._format_transcript(transcript)}\n\n"
            "규칙:\n"
            "- 슬라이드에 있으나 전사에서 언급되지 않은 지점, 또는 언급했으나 근거·수치가 약한 주장을 우선 겨냥한다.\n"
            "- 질문끼리 관점이 겹치지 않게 한다.\n"
            "- persona는 위 목록 값 중 하나, 그 페르소나의 말투를 반영한다.\n"
            "- 각 질문의 근거를 slides(페이지 번호 배열)와 transcript_starts(전사 구간 시작 초 배열)로 표기한다. "
            "근거가 없으면 빈 배열로 둔다. 존재하지 않는 페이지·시간을 지어내지 않는다.\n"
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
        if not transcript:
            return "(전사 없음)"
        out, used = [], 0
        for seg in transcript:
            line = f"[{_mmss(float(seg.get('start', 0)))}] {str(seg.get('text', '')).strip()}"
            used += len(line)
            if used > _TRANSCRIPT_CHAR_LIMIT:
                break
            out.append(line)
        return "\n".join(out)

    # ── evidence 사후검증 ───────────────────────────────────────────────────

    @staticmethod
    def _transcript_range(transcript: list[dict] | None) -> tuple[float, float] | None:
        if not transcript:
            return None
        starts = [float(s.get("start", 0)) for s in transcript]
        ends = [float(s.get("end", s.get("start", 0))) for s in transcript]
        return (min(starts), max(ends))

    @staticmethod
    def _clean_evidence(
        slides: list[int], starts: list[float],
        valid_pages: set, t_range: tuple[float, float] | None,
    ) -> Evidence:
        # 환각 근거 제거: 실제 page·시간 범위 밖은 버린다(질문 텍스트는 유지).
        pages = [p for p in dict.fromkeys(slides) if p in valid_pages]
        refs: list[TranscriptRef] = []
        if t_range is not None:
            lo, hi = t_range
            for st in dict.fromkeys(starts):
                if lo <= st <= hi:
                    refs.append(TranscriptRef(start=float(st)))
        return Evidence(slides=pages, transcript_refs=refs)

    # ── 공통 생성 ───────────────────────────────────────────────────────────

    async def _generate(
        self, prompt: str, schema: type[_SchemaT], *, temperature: float
    ) -> _SchemaT:
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
            ),
        )
        if isinstance(response.parsed, schema):
            return response.parsed
        # SDK 파싱이 비어 오는 경우(드묾) 텍스트에서 직접 복원.
        return schema.model_validate(json.loads(response.text or ""))
