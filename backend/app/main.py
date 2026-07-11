from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes import auth, speeches, teams
from app.core.config import settings
from app.db.session import get_db

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(teams.router)
app.include_router(speeches.router)


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
