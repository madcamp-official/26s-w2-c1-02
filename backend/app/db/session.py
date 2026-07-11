"""DB 엔진 + 요청 단위 세션 주입 (작업 2-3).

라우터에서 `db: Session = Depends(get_db)`로 받아 쓴다.
요청 1건 = 세션 1개 — 응답이 나가면 finally에서 반드시 반납된다.

기존 인메모리 store.py는 지우지 않는다(workflow 가이드라인 2 — mock 경로 유지).
라우터를 실제 DB로 옮길 때 이 모듈로 하나씩 갈아탄다.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings

# 앱 전체에서 엔진은 하나 — 내부적으로 커넥션 풀을 관리한다.
# pool_pre_ping: 끊어진 연결을 쓰기 전에 감지해 재연결 (DB 재시작 등에 강해짐)
engine = create_engine(settings.database_url, pool_pre_ping=True)

# 세션 공장: 호출할 때마다 새 세션을 만든다
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 의존성. commit은 각 라우터가 명시적으로 한다 (암묵적 commit 없음)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
