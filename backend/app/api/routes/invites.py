"""초대 — 이메일 · 링크 · 토큰 수락/거절 (작업 4-5, api-spec §3.1).

두 개의 라우터로 나뉜다:
- router       : 팀 스코프 (`/teams/{id}/invites*`, `/teams/{id}/invites/link`)
                 권한은 멤버/팀장 가드로 (이메일 초대·목록·취소=멤버, 링크 회전·삭제=팀장)
- token_router : 토큰 스코프 (`/invites/{token}`) — 미리보기는 인증 불필요(H),
                 수락/거절은 인증 필요

메일 발송은 스코프 컷으로 생략하고 token·url을 응답/로그로 노출한다.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_team_leader, require_team_member
from app.core.errors import ApiError
from app.db import models
from app.db.enums import InviteStatus
from app.db.session import get_db
from app.schemas.invite import (
    AcceptResponse,
    EmailInviteOut,
    EmailInviteRequest,
    InviteLinkOut,
    InvitePreview,
)

router = APIRouter(prefix="/teams", tags=["invites"])
token_router = APIRouter(prefix="/invites", tags=["invites"])

logger = logging.getLogger("rehearsal.invites")

_EMAIL_INVITE_TTL = timedelta(days=7)
_LINK_TTL = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _preview_url(request: Request, token: str) -> str:
    """공유용 초대 URL — 미리보기 엔드포인트로 해석되는 절대 URL."""
    return str(request.url_for("preview_invite", token=token))


def _email_invite_out(inv: models.TeamEmailInvite, request: Request) -> EmailInviteOut:
    return EmailInviteOut(
        id=inv.id, email=inv.email, status=inv.status,
        token=inv.token, url=_preview_url(request, inv.token),
        expires_at=inv.expires_at, created_at=inv.created_at,
    )


def _link_out(link: models.TeamInviteLink, request: Request) -> InviteLinkOut:
    return InviteLinkOut(
        token=link.token, url=_preview_url(request, link.token),
        expires_at=link.expires_at,
    )


# ── 이메일 초대 (권한: 멤버) ───────────────────────────────────────────

@router.post("/{team_id}/invites", response_model=EmailInviteOut, status_code=201)
def create_email_invite(
    request: Request,
    body: EmailInviteRequest,
    team: models.Team = Depends(require_team_member),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EmailInviteOut:
    """이메일 초대 생성. 발송은 생략하고 token을 응답·로그로 노출.
    같은 팀·같은 이메일 pending 중복은 부분 유니크(team_email_invites_pending_key)가 차단 → 409."""
    inv = models.TeamEmailInvite(
        team_id=team.id, email=body.email,
        token=secrets.token_urlsafe(32), invited_by=user.id,
        expires_at=_now() + _EMAIL_INVITE_TTL,
    )
    db.add(inv)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ApiError(409, "INVITE_ALREADY_PENDING", "이미 초대한 이메일이에요.")
    db.refresh(inv)
    logger.info("이메일 초대 생성(발송 생략) team=%s email=%s token=%s",
                team.id, inv.email, inv.token)
    return _email_invite_out(inv, request)


@router.get("/{team_id}/invites", response_model=list[EmailInviteOut])
def list_email_invites(
    request: Request,
    team: models.Team = Depends(require_team_member),
    db: Session = Depends(get_db),
) -> list[EmailInviteOut]:
    """대기 중(pending) 이메일 초대 목록."""
    rows = db.scalars(
        select(models.TeamEmailInvite)
        .where(models.TeamEmailInvite.team_id == team.id,
               models.TeamEmailInvite.status == InviteStatus.pending)
        .order_by(models.TeamEmailInvite.created_at.desc())
    ).all()
    return [_email_invite_out(r, request) for r in rows]


# ── 링크 초대 (조회=멤버, 회전·삭제=팀장) ──
# 주의: '/link'는 아래 '/{invite_id}'보다 먼저 선언해야 link가 invite_id로 안 잡힌다.

@router.post("/{team_id}/invites/link", response_model=InviteLinkOut, status_code=201)
def rotate_invite_link(
    request: Request,
    team: models.Team = Depends(require_team_leader),
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InviteLinkOut:
    """링크 생성/회전. 같은 트랜잭션에서 기존 활성 링크를 revoke한 뒤 새 링크 insert.
    team_invite_links_active_key(활성 1개)는 즉시 검사되므로 UPDATE를 flush로 먼저 내보낸다."""
    active = db.scalar(
        select(models.TeamInviteLink)
        .where(models.TeamInviteLink.team_id == team.id,
               models.TeamInviteLink.revoked_at.is_(None))
    )
    if active is not None:
        active.revoked_at = _now()
        db.flush()  # 새 링크 INSERT 전에 UPDATE 반영 → 활성 1개 유니크 위반 방지
    link = models.TeamInviteLink(
        team_id=team.id, token=secrets.token_urlsafe(32),
        created_by=user.id, expires_at=_now() + _LINK_TTL,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    logger.info("초대 링크 회전 team=%s token=%s", team.id, link.token)
    return _link_out(link, request)


@router.get("/{team_id}/invites/link", response_model=InviteLinkOut | None)
def get_active_invite_link(
    request: Request,
    team: models.Team = Depends(require_team_member),
    db: Session = Depends(get_db),
) -> InviteLinkOut | None:
    """현재 활성 링크 또는 null."""
    link = db.scalar(
        select(models.TeamInviteLink)
        .where(models.TeamInviteLink.team_id == team.id,
               models.TeamInviteLink.revoked_at.is_(None))
    )
    return _link_out(link, request) if link is not None else None


@router.delete("/{team_id}/invites/link", status_code=204)
def revoke_invite_link(
    team: models.Team = Depends(require_team_leader),
    db: Session = Depends(get_db),
) -> None:
    """활성 링크 비활성화(멱등 — 없으면 204)."""
    link = db.scalar(
        select(models.TeamInviteLink)
        .where(models.TeamInviteLink.team_id == team.id,
               models.TeamInviteLink.revoked_at.is_(None))
    )
    if link is not None:
        link.revoked_at = _now()
        db.commit()


@router.delete("/{team_id}/invites/{invite_id}", status_code=204)
def cancel_email_invite(
    invite_id: str,
    team: models.Team = Depends(require_team_member),
    db: Session = Depends(get_db),
) -> None:
    """이메일 초대 취소. pending이면 canceled로 (부분 유니크가 풀려 재초대 가능)."""
    inv = db.get(models.TeamEmailInvite, invite_id)
    if inv is None or inv.team_id != team.id:
        raise ApiError(404, "INVITE_NOT_FOUND", "초대를 찾을 수 없어요.")
    if inv.status == InviteStatus.pending:
        inv.status = InviteStatus.canceled
        inv.responded_at = _now()
        db.commit()


# ── 토큰 스코프: 미리보기(인증 불필요) · 수락/거절(인증 필요) ─────────────

def _assert_email_usable(inv: models.TeamEmailInvite) -> None:
    if inv.status != InviteStatus.pending:
        raise ApiError(409, "INVITE_INVALID", "이미 처리되었거나 취소된 초대예요.")
    if inv.expires_at < _now():
        raise ApiError(410, "INVITE_EXPIRED", "초대가 만료됐어요.")


def _assert_link_usable(link: models.TeamInviteLink) -> None:
    if link.revoked_at is not None:
        raise ApiError(409, "INVITE_INVALID", "비활성화된 초대 링크예요.")
    if link.expires_at < _now():
        raise ApiError(410, "INVITE_EXPIRED", "초대 링크가 만료됐어요.")


def _resolve_token(token: str, db: Session):
    """token으로 이메일 초대 또는 링크를 찾아 (team, email_invite|None, link|None)을 반환.
    유효성(만료·무효)까지 검사. 못 찾으면 409 INVITE_INVALID."""
    email_inv = db.scalar(
        select(models.TeamEmailInvite).where(models.TeamEmailInvite.token == token)
    )
    if email_inv is not None:
        _assert_email_usable(email_inv)
        return db.get(models.Team, email_inv.team_id), email_inv, None

    link = db.scalar(
        select(models.TeamInviteLink).where(models.TeamInviteLink.token == token)
    )
    if link is not None:
        _assert_link_usable(link)
        return db.get(models.Team, link.team_id), None, link

    raise ApiError(409, "INVITE_INVALID", "유효하지 않은 초대예요.")


@token_router.get("/{token}", response_model=InvitePreview)
def preview_invite(token: str, db: Session = Depends(get_db)) -> InvitePreview:
    """초대 미리보기(인증 불필요) — 팀명·인원·발표 수."""
    team, _email, _link = _resolve_token(token, db)
    member_count = db.scalar(
        select(func.count()).select_from(models.TeamMember)
        .where(models.TeamMember.team_id == team.id)
    )
    session_count = db.scalar(
        select(func.count()).select_from(models.RehearsalSession)
        .where(models.RehearsalSession.team_id == team.id)
    )
    return InvitePreview(team_id=team.id, team_name=team.name,
                         member_count=member_count, session_count=session_count)


@token_router.post("/{token}/accept", response_model=AcceptResponse)
def accept_invite(
    token: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AcceptResponse:
    """초대 수락 → 팀 합류. 이미 멤버면 멱등. 이메일 초대는 status=accepted로 갱신."""
    team, email_inv, _link = _resolve_token(token, db)
    if db.get(models.TeamMember, (team.id, user.id)) is None:
        db.add(models.TeamMember(team_id=team.id, user_id=user.id))
    if email_inv is not None:
        email_inv.status = InviteStatus.accepted
        email_inv.responded_at = _now()
    db.commit()
    return AcceptResponse(team_id=team.id)


@token_router.post("/{token}/decline", status_code=204)
def decline_invite(
    token: str,
    user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """초대 거절. 이메일 초대는 status=declined로 기록.
    링크 초대는 개인별 상태가 없어 기록할 것이 없다(no-op)."""
    _team, email_inv, _link = _resolve_token(token, db)
    if email_inv is not None:
        email_inv.status = InviteStatus.declined
        email_inv.responded_at = _now()
        db.commit()
