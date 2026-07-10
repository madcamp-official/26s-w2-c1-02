from fastapi import APIRouter, HTTPException

from app.db.store import store
from app.schemas.qna import QnaItem
from app.schemas.speech import Speech
from app.services.llm.factory import get_llm_provider

router = APIRouter(prefix="/speeches", tags=["speeches"])


@router.get("/{speech_id}", response_model=Speech)
async def get_speech(speech_id: str) -> Speech:
    speech = store.get_speech(speech_id)
    if speech is None:
        raise HTTPException(status_code=404, detail="speech not found")
    return speech


@router.post("/{speech_id}/qna", response_model=list[QnaItem])
async def generate_qna(speech_id: str) -> list[QnaItem]:
    """발표 종료 후 LLM으로 질의응답 질문을 생성한다.

    지금은 Mock 제공자가 더미 질문을 반환한다.
    """
    speech = store.get_speech(speech_id)
    if speech is None:
        raise HTTPException(status_code=404, detail="speech not found")

    llm = get_llm_provider()
    return await llm.generate_questions(
        speech_name=speech.name,
        material_text=None,  # TODO: 업로드된 PDF 텍스트 추출 후 전달
        audience_type=speech.audience_type,
        audience_detail=speech.audience_detail,
        count=speech.question_count,
    )
