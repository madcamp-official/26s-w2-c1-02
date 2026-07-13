from fastapi import APIRouter, HTTPException

from app.db.enums import QuestionerPersona
from app.db.store import store
from app.schemas.common import AudienceType
from app.schemas.qna import QuestionDraft
from app.schemas.speech import Speech
from app.services.llm.factory import get_llm_provider

router = APIRouter(prefix="/speeches", tags=["speeches"])

# 레거시 Speech(audience_type 4종) → QuestionerPersona(5종) 매핑.
# 이 라우터는 팀원2의 /sessions/{id}/qna/generate 로 대체될 스캐폴드다.
_AUDIENCE_TO_PERSONA = {
    AudienceType.teto: QuestionerPersona.teto,
    AudienceType.egen: QuestionerPersona.egen,
    AudienceType.kkondae: QuestionerPersona.kkondae,
    AudienceType.etc: QuestionerPersona.egen,
}


@router.get("/{speech_id}", response_model=Speech)
async def get_speech(speech_id: str) -> Speech:
    speech = store.get_speech(speech_id)
    if speech is None:
        raise HTTPException(status_code=404, detail="speech not found")
    return speech


@router.post("/{speech_id}/qna", response_model=list[QuestionDraft])
async def generate_qna(speech_id: str) -> list[QuestionDraft]:
    """발표 종료 후 LLM으로 질의응답 질문을 생성한다(레거시 스캐폴드).

    지금은 Mock 제공자가 더미 질문을 반환한다. slides/transcript는 세션 파이프라인
    (팀원2 /qna/generate)에서 전달되며, 이 엔드포인트에는 아직 연결돼 있지 않다.
    """
    speech = store.get_speech(speech_id)
    if speech is None:
        raise HTTPException(status_code=404, detail="speech not found")

    llm = get_llm_provider()
    return await llm.generate_questions(
        speech_name=speech.name,
        slides=None,       # TODO: 업로드된 PDF slides 전달
        transcript=None,   # TODO: STT transcript 전달
        personas=[_AUDIENCE_TO_PERSONA[speech.audience_type]],
        count=speech.question_count,
    )
