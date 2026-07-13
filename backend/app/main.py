from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import (
    auth, files, invites, materials, qna, recordings, sessions, speeches, teams,
)
from app.core.config import settings
from app.core.errors import ApiError, api_error_handler, validation_error_handler
from app.db.session import get_db
from app.services import stt_queue


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 서버 재시작으로 큐(인메모리)가 비었을 때, 미완료 STT 잡을 다시 큐에 넣는다.
    stt_queue.recover()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

# api-spec §1.1 에러 포맷: 라우터가 raise ApiError(...) 하면 여기서 JSON으로 변환
app.add_exception_handler(ApiError, api_error_handler)
# Pydantic 검증 실패(422)도 같은 포맷으로 (code=VALIDATION_ERROR)
app.add_exception_handler(RequestValidationError, validation_error_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# api-spec §1: Base URL = /api/v1 (refresh 쿠키의 Path=/api/v1/auth도 여기에 의존)
API_V1 = "/api/v1"
app.include_router(auth.router, prefix=API_V1)
app.include_router(teams.router, prefix=API_V1)
app.include_router(invites.router, prefix=API_V1)        # /teams/{id}/invites*
app.include_router(invites.token_router, prefix=API_V1)  # /invites/{token}*
app.include_router(speeches.router, prefix=API_V1)
app.include_router(files.router, prefix=API_V1)          # /files/{key}?expires=&sig=
app.include_router(sessions.router, prefix=API_V1)       # /teams/{id}/sessions, /sessions/{id}
app.include_router(materials.router, prefix=API_V1)      # /sessions/{id}/material
app.include_router(recordings.router, prefix=API_V1)     # /sessions/{id}/recording
app.include_router(qna.router, prefix=API_V1)            # /sessions/{id}/qna/generate


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "llm_provider": settings.llm_provider}


@app.get("/health/db", tags=["meta"])
def health_db(db: Session = Depends(get_db)) -> dict:
    """DB 세션 주입(get_db) 동작 확인용. 접속한 DB 이름과 테이블 수를 반환."""
    row = db.execute(
        text(
            "SELECT current_database(), current_user, "
            "(SELECT count(*) FROM pg_tables WHERE schemaname = 'public')"
        )
    ).one()
    return {"status": "ok", "database": row[0], "user": row[1], "tables": row[2]}
