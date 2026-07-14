"""테스트 공통 설정.

테스트는 결정론적 mock LLM을 전제한다(스냅샷·꼬리질문 생성 여부 단언).
개발용 .env가 LLM_PROVIDER=gemini여도 테스트가 실 API를 때리지 않도록
환경변수를 기본 mock으로 고정한다 — 셸에서 LLM_PROVIDER=gemini를 명시하면
그쪽이 우선이라 라이브 검수도 가능하다. (env var > .env, pydantic-settings)

app 모듈 임포트 전에 실행돼야 하므로 여기(conftest 최상단)에서 설정한다.
"""

import os

os.environ.setdefault("LLM_PROVIDER", "mock")
# 이메일도 동일 규율 — 테스트가 실 SMTP를 때리지 않게 mock 고정 (email-verification-plan 작업 6)
os.environ.setdefault("EMAIL_PROVIDER", "mock")


def mark_email_verified(username: str) -> None:
    """가입 직후 유저를 인증 완료 상태로 만든다 — 로그인 차단(403) 우회용 공용 헬퍼.

    로그인 강제 도입(email-verification-plan)으로 signup→login 2단계 헬퍼가 전부
    깨지므로, 각 테스트 파일의 가입 헬퍼가 signup 직후 이걸 한 번 호출한다.
    인증 플로우 자체를 검증하는 test_email_verify.py에서는 쓰지 말 것.
    """
    from datetime import datetime, timezone

    from sqlalchemy import func, update

    from app.db.models import User
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.execute(
            update(User)
            .where(func.lower(User.username) == username.lower())
            .values(email_verified_at=datetime.now(timezone.utc))
        )
        db.commit()
