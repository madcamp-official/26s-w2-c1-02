from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 설정. 환경변수/.env 에서 로드."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Rehearsal.io API"

    # 쉼표로 구분된 CORS 오리진. 개발 편의를 위해 localhost 전체 허용이 기본.
    cors_origins: str = "http://localhost:*,http://127.0.0.1:*"

    # PostgreSQL 접속 URL (.env의 DATABASE_URL). 미설정 시 로컬 개발 기본값.
    database_url: str = "postgresql+psycopg://rehearsal:rehearsal123@localhost:5432/rehearsal_dev"

    # JWT 서명 시크릿. 반드시 .env에서 각자 값으로 설정할 것 (기본값은 개발용 임시값).
    # 생성: python -c "import secrets; print(secrets.token_hex(32))"
    jwt_secret: str = "INSECURE-DEV-ONLY-CHANGE-ME-IN-ENV"
    # access 토큰 수명(초). api-spec §2 응답의 expires_in과 일치해야 함.
    jwt_access_expires_seconds: int = 900
    # refresh 토큰 수명(초). 기본 14일 — 자동 로그인 유지 기간.
    refresh_expires_seconds: int = 14 * 24 * 3600

    # 파일 스토리지 (작업 5, A10). 업로드 파일이 저장되는 로컬 디렉터리.
    # 상대경로면 backend/ 기준으로 해석된다.
    storage_dir: str = "storage"
    # 서명 URL(*_url) 서명·검증용 시크릿. 재시작해도 URL이 유효하려면 값이 고정이어야 함.
    storage_url_secret: str = "INSECURE-DEV-STORAGE-CHANGE-ME"
    # 서명 URL 유효시간(초). 기본 1시간 — 재생 중 만료되지 않을 만큼.
    signed_url_expires_seconds: int = 3600

    # LLM 제공자 선택 (mock | gemini)
    llm_provider: str = "mock"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    # Vertex AI 엔드포인트 사용 여부. AI Studio 무료 키도 이제 "AQ." 형식으로 발급되어
    # 키 접두사로 경로를 추정할 수 없다 — 무료(Gemini API) 키면 false(기본), Vertex 키만 true.
    gemini_use_vertex: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
