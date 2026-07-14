"""발표 세션 CRUD (작업 2-2, api-spec §4.1 · db-schema §3.3).

권한(작업 1 Depends 재사용):
- GET  /teams/{team_id}/sessions  : 멤버
- POST /teams/{team_id}/sessions  : 멤버 (생성자 = owner)
- GET  /sessions/{session_id}     : 멤버
- PATCH /sessions/{session_id}    : owner + draft일 때만
- DELETE /sessions/{session_id}   : owner 또는 팀장 (+ 스토리지 파일 정리)
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    require_session_member,
    require_session_owner,
    require_session_owner_or_leader,
    require_team_member,
)
from app.core import storage
from app.core.errors import ApiError
from app.db import models
from app.db.enums import AsyncStatus, SessionStatus
from app.db.session import get_db
from app.services.storage_cleanup import session_storage_keys
from app.schemas.session import (
    MaterialStatusOut,
    RecordingStatusOut,
    ReportStatusOut,
    SessionCreateRequest,
    SessionDetail,
    SessionListOut,
    SessionUpdateRequest,
    TranscriptStatusOut,
)

router = APIRouter(tags=["sessions"])


# ── 목록 · 생성 (팀 스코프) ───────────────────────────────────────────

@router.get("/teams/{team_id}/sessions", response_model=SessionListOut)
def list_sessions(
    team: models.Team = Depends(require_team_member),
    db: Session = Depends(get_db),
) -> SessionListOut:
    """세션 목록 (멤버). 항목은 상세와 동일 형태 — FE가 풀 Session으로 파싱한다."""
    rows = db.scalars(
        select(models.RehearsalSession)
        .where(models.RehearsalSession.team_id == team.id)
        .order_by(models.RehearsalSession.created_at.desc())  # sessions_team_idx
    ).all()
    return SessionListOut(items=[_to_detail(s, db) for s in rows])


@router.post("/teams/{team_id}/sessions", response_model=SessionDetail, status_code=201)
def create_session(
    body: SessionCreateRequest,
    team: models.Team = Depends(require_team_member),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SessionDetail:
    """draft 세션 생성. 생성자가 owner(발표자). status는 DB 기본값 'draft'."""
    session = models.RehearsalSession(
        team_id=team.id, owner_id=user.id, name=body.name,
        personas=body.personas, question_count=body.question_count,
        time_limit_minutes=body.time_limit_minutes, mode=body.mode,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _to_detail(session, db)


# ── 상세 · 수정 · 삭제 (세션 스코프) ──────────────────────────────────

@router.get("/sessions/{session_id}", response_model=SessionDetail)
def get_session(
    session: models.RehearsalSession = Depends(require_session_member),
    db: Session = Depends(get_db),
) -> SessionDetail:
    return _to_detail(session, db)


@router.patch("/sessions/{session_id}", response_model=SessionDetail)
def update_session(
    body: SessionUpdateRequest,
    session: models.RehearsalSession = Depends(require_session_owner),
    db: Session = Depends(get_db),
) -> SessionDetail:
    """설정 수정 — draft일 때만 (녹음·질문 생성이 시작되면 설정은 고정)."""
    if session.status != SessionStatus.draft:
        raise ApiError(409, "SESSION_NOT_DRAFT",
                       "이미 시작된 발표는 설정을 바꿀 수 없어요.")
    changes = body.model_dump(exclude_unset=True)  # 보낸 필드만 반영
    for field, value in changes.items():
        setattr(session, field, value)
    db.commit()
    db.refresh(session)
    return _to_detail(session, db)


@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session: models.RehearsalSession = Depends(require_session_owner_or_leader),
    db: Session = Depends(get_db),
) -> None:
    """세션 삭제. DB는 CASCADE, 스토리지 파일은 앱이 정리 (db-schema §7.3).

    순서: storage_key 먼저 수집 → DB 커밋(CASCADE) → 커밋 성공 후 파일 삭제.
    """
    keys = session_storage_keys(db, session.id)
    db.delete(session)
    db.commit()
    for key in keys:  # 커밋 성공 후에만 파일 삭제 (실패분은 best-effort)
        storage.delete(key)


# ── 헬퍼 ──────────────────────────────────────────────────────────────

def _to_detail(session: models.RehearsalSession, db: Session) -> SessionDetail:
    """세션 + 하위 리소스 상태 → SessionDetail (api-spec §4.1 형태).

    audio_url은 storage_key에서 서명 URL로 파생(A10). report는 qna/end 전 null(A7)."""
    material = db.get(models.Material, session.id)
    recording = db.get(models.Recording, session.id)
    transcript = db.get(models.Transcript, session.id)
    report = db.get(models.Report, session.id)

    material_out = None
    if material is not None:
        slide_count = material.page_count
        if slide_count is None and material.slides is not None:
            slide_count = len(material.slides)
        material_out = MaterialStatusOut(status=material.status, slide_count=slide_count)

    recording_out = None
    if recording is not None:
        recording_out = RecordingStatusOut(
            status=recording.status,
            duration_seconds=recording.duration_seconds,
            audio_url=storage.signed_url(recording.storage_key),
        )

    transcript_out = (
        TranscriptStatusOut(status=transcript.status) if transcript is not None else None
    )

    return SessionDetail(
        id=session.id, team_id=session.team_id, owner_id=session.owner_id,
        name=session.name, status=session.status, personas=session.personas,
        question_count=session.question_count, time_limit_minutes=session.time_limit_minutes,
        mode=session.mode, material=material_out, recording=recording_out,
        transcript=transcript_out,
        report=ReportStatusOut(status=report.status) if report is not None else None,
        created_at=session.created_at,
    )
