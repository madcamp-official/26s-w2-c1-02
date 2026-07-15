"""비밀번호 재설정 코드 발급 (아이디/비밀번호 찾기, api-spec §2).

email_verification.issue_verification_code와 동일한 규율:
코드 평문은 메일로만 나가고 DB엔 bcrypt 해시만 저장한다. 검증(대조·만료·시도 제한)은
auth 라우트의 POST /auth/password/reset이 수행한다.

TTL·시도 제한·쿨다운 상수는 email_verification의 것을 그대로 재사용한다 —
두 흐름의 위협 모델(메일로 온 6자리 코드 브루트포스)이 같기 때문이다.
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db import models
from app.services.email_verification import CODE_TTL


def issue_reset_code(db: Session, user: models.User) -> str:
    """새 비밀번호 재설정 코드를 발급하고 커밋한다. 반환된 평문은 메일 발송에만 쓸 것.

    발급 전에 해당 유저의 유효 코드를 전부 소비 처리한다 — 재발송 후 옛 코드로
    재설정되는 구멍 차단. 유저당 유효 코드는 항상 최대 1개 (issue_verification_code와 동일).
    """
    now = datetime.now(timezone.utc)
    db.execute(
        update(models.PasswordReset)
        .where(
            models.PasswordReset.user_id == user.id,
            models.PasswordReset.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    code = f"{secrets.randbelow(1_000_000):06d}"  # CSPRNG — random 모듈 금지
    db.add(models.PasswordReset(
        user_id=user.id,
        code_hash=hash_password(code),
        expires_at=now + CODE_TTL,
    ))
    db.commit()
    return code
