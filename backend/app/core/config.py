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

    # 이메일 발송 제공자 (mock | smtp). mock은 발송 대신 로그에 코드를 출력한다 —
    # SMTP 없이 전체 개발·테스트 가능. smtp는 배포 VM에서만 켠다 (plan §7-1).
    email_provider: str = "mock"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587            # STARTTLS
    smtp_user: str = ""             # 보내는 gmail 주소
    smtp_password: str = ""         # gmail 앱 비밀번호 — .env에만, 커밋 금지

    # LLM 제공자 선택 (mock | gemini)
    llm_provider: str = "mock"
    gemini_api_key: str = ""
    # 버전을 고정하면 구글이 해당 모델을 "no longer available to new users"로 게이팅할 때
    # 404로 질문 생성이 전면 실패한다(gemini-2.5-flash가 그렇게 막혀 운영 장애 발생).
    # 항상 사용 가능한 최신 flash 별칭을 기본으로 둔다.
    gemini_model: str = "gemini-flash-latest"
    # Vertex AI 엔드포인트 사용 여부. AI Studio 무료 키도 이제 "AQ." 형식으로 발급되어
    # 키 접두사로 경로를 추정할 수 없다 — 무료(Gemini API) 키면 false(기본), Vertex 키만 true.
    gemini_use_vertex: bool = False
    # Gemini 호출 1건 상한(초). 기본 미설정 시 SDK 기본이 사실상 무제한이라, 응답이
    # 늦어지면 질문 생성 잡이 오래 매달린다. 이 시간이 지나면 SDK가 에러를 던지고
    # run_generate가 세션을 failed로 흡수 → 폴링에서 '생성 실패'로 빠르게 노출된다.
    gemini_timeout_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
