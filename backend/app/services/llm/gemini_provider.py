"""Gemini 제공자 — LLMProvider의 첫 실제 구현.

google-genai SDK를 사용한다. AI Studio 키("AIza…")와 Vertex AI express
mode 키("AQ.…") 모두 지원하며, 키 접두사로 엔드포인트를 자동 선택한다.
출력은 response_schema로 JSON을 강제해 QnaItem으로 변환한다.
"""

import json
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from app.core.config import settings
from app.schemas.common import AudienceType
from app.schemas.qna import QnaItem
from app.services.llm.base import LLMProvider

_MAX_FOLLOW_UP_DEPTH = 3

_SchemaT = TypeVar("_SchemaT", bound=BaseModel)

# 프롬프트에 넣는 발표 자료 텍스트 상한(대략 토큰 폭주 방지용).
_MATERIAL_CHAR_LIMIT = 15_000

_AUDIENCE_STYLE: dict[AudienceType, str] = {
    AudienceType.teto: "직설적이고 도전적인 청중. 논리 허점과 근거 부족을 정면으로 추궁한다.",
    AudienceType.egen: "부드럽고 공감형인 청중. 맥락, 배경, 발표자의 의도를 궁금해한다.",
    AudienceType.kkondae: "권위적인 연장자 청중. 자기 경험에 빗대어 실무 디테일과 기본기를 확인하려 든다.",
    AudienceType.etc: "일반 청중. 발표 내용 전반에 고르게 관심이 있다.",
}


class _QuestionsOut(BaseModel):
    questions: list[str]


class _FollowUpOut(BaseModel):
    # 꼬리질문이 불필요하다고 판단하면 null.
    follow_up: str | None = None


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
        material_text: str | None,
        audience_type: AudienceType,
        audience_detail: str | None,
        count: int,
    ) -> list[QnaItem]:
        material = (material_text or "").strip()[:_MATERIAL_CHAR_LIMIT]
        prompt = (
            "당신은 발표 리허설 서비스의 예상 질문 생성기입니다.\n"
            f"아래 발표에 대해 청중이 던질 법한 질문을 정확히 {count}개, 한국어로 만드세요.\n\n"
            f"[발표 제목] {speech_name}\n"
            f"[청중 유형] {_AUDIENCE_STYLE[audience_type]}\n"
            + (f"[청중 상세] {audience_detail}\n" if audience_detail else "")
            + "[발표 자료 전문]\n"
            + (material if material else "(자료 없음 — 제목만으로 추정)")
            + "\n\n규칙:\n"
            "- 자료에 있으나 설명이 부족할 법한 부분, 근거가 약한 주장을 우선 겨냥한다.\n"
            "- 질문끼리 관점이 겹치지 않게 한다 (개념·근거·수치·한계 등).\n"
            "- 각 질문은 한두 문장으로 간결하게, 청중 유형의 말투를 반영한다.\n"
        )
        out = await self._generate(prompt, _QuestionsOut, temperature=0.7)
        return [
            QnaItem(index=i + 1, question=q.strip())
            for i, q in enumerate(out.questions[:count])
            if q.strip()
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
        prompt = (
            "발표 질의응답에서 발표자의 답변을 보고 꼬리질문이 필요한지 판단하세요.\n\n"
            f"[원 질문] {question}\n"
            f"[발표자 답변] {answer}\n\n"
            "답변이 충분히 구체적이면 follow_up을 null로 두세요.\n"
            "근거·수치·설명이 빈약하면 그 지점을 파고드는 한국어 꼬리질문 1개를 만드세요.\n"
            "답변은 STT 원문이라 간투사(어, 음)나 비문이 섞여 있어도 내용으로만 판단하세요.\n"
        )
        out = await self._generate(prompt, _FollowUpOut, temperature=0.5)
        if not out.follow_up or not out.follow_up.strip():
            return None
        return QnaItem(
            index=0,
            question=out.follow_up.strip(),
            follow_up_depth=depth + 1,
        )

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
