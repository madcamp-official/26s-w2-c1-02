"""삭제 시 정리할 오브젝트 스토리지 key 수집 (db-schema §7.3).

DB는 FK CASCADE로 행을 지우지만 스토리지 파일은 지우지 못한다. 그래서 삭제 API는
**커밋 전에 storage_key를 모아뒀다가, 커밋 성공 후 파일을 지운다.**
세션 단건 삭제(sessions.py)와 팀 삭제(teams.py)가 이 수집 로직을 공유한다.
"""

from collections.abc import Iterable

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.db import models


def _storage_keys_for_sessions(
    db: Session, session_ids: Iterable[str] | Select
) -> list[str]:
    """주어진 세션들에 딸린 모든 파일 storage_key.

    session_ids는 리스트(단건 삭제) 또는 세션 id 서브쿼리(팀 삭제) 둘 다 받는다
    (`.in_()`이 양쪽 모두 처리). 대상: 자료·녹음·실시간청크·질문TTS·답변오디오.
    """
    keys: list[str] = []

    for (k,) in db.execute(
        select(models.Material.storage_key)
        .where(models.Material.session_id.in_(session_ids))
    ):
        if k:
            keys.append(k)

    for (k,) in db.execute(
        select(models.Recording.storage_key)
        .where(models.Recording.session_id.in_(session_ids))
    ):
        if k:
            keys.append(k)

    for (k,) in db.execute(
        select(models.RecordingChunk.storage_key)
        .where(models.RecordingChunk.session_id.in_(session_ids))
    ):
        if k:
            keys.append(k)

    # 질문 TTS + 답변 오디오 (질문 LEFT JOIN 답변)
    for tts_key, answer_key in db.execute(
        select(models.Question.tts_storage_key, models.Answer.audio_storage_key)
        .join(models.Answer, models.Answer.question_id == models.Question.id, isouter=True)
        .where(models.Question.session_id.in_(session_ids))
    ):
        if tts_key:
            keys.append(tts_key)
        if answer_key:
            keys.append(answer_key)

    return keys


def session_storage_keys(db: Session, session_id: str) -> list[str]:
    """세션 단건에 딸린 모든 파일 storage_key (DELETE /sessions/{id})."""
    return _storage_keys_for_sessions(db, [session_id])


def team_storage_keys(db: Session, team_id: str) -> list[str]:
    """팀에 속한 모든 세션의 파일 storage_key (DELETE /teams/{id})."""
    session_ids = select(models.RehearsalSession.id).where(
        models.RehearsalSession.team_id == team_id
    )
    return _storage_keys_for_sessions(db, session_ids)
