"""이메일 인증코드 발급 (email-verification-plan 작업 4).

코드 평문은 메일로만 나간다 — DB에는 bcrypt 해시만 저장(비밀번호와 동일 규율),
API 응답·로그에 노출 금지(EMAIL_PROVIDER=mock의 발송 대체 로그만 예외).
검증(대조·만료·시도 제한)은 auth 라우트의 POST /auth/email/verify가 수행한다.
"""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import models

# TTL·제한 상수 (plan §4-2 근거 그대로)
CODE_TTL = timedelta(minutes=10)         # 메일 지연 감안 + 방치된 코드 최소화
MAX_ATTEMPTS = 5                         # 100만 경우 ÷ 5회 = 무차별 대입 기대성공률 0.0005%
RESEND_COOLDOWN = timedelta(seconds=60)  # 발송 스팸·Gmail 일 500통 쿼터 보호


def issue_verification_code(db: Session, user: models.User) -> str:
    """새 인증코드를 발급하고 커밋한다. 반환된 평문은 메일 발송에만 쓸 것.

    발급 전에 해당 유저의 유효 코드를 전부 소비 처리한다 — 재발송 후
    옛 코드로 인증되는 구멍 차단. 유저당 유효 코드는 항상 최대 1개.
    """
    now = datetime.now(timezone.utc)
    db.execute(
        update(models.EmailVerification)
        .where(
            models.EmailVerification.user_id == user.id,
            models.EmailVerification.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"  # CSPRNG — random 모듈 금지
    db.add(models.EmailVerification(
        user_id=user.id,
        code_hash=hash_password(code),
        expires_at=now + CODE_TTL,
    ))
    db.commit()
    return code
