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
    # (이 상한은 재시도 1회당 적용된다 — gemini_max_attempts 참고.)
    gemini_timeout_seconds: int = 60
    # Gemini 호출 총 시도 횟수(최초 호출 포함). google-genai는 retry_options를 안 주면
    # stop_after_attempt(1)로 "재시도 없음"이 기본이라, Gemini의 일시적 서버 오류
    # (503 UNAVAILABLE '고수요'/504 DEADLINE_EXCEEDED/429/500/502)가 한 번만 떠도 질문
    # 생성이 곧장 failed로 떨어져 사용자가 '다시 생성'을 반복해야 했다(2026-07-15 장애).
    # 1보다 크면 지수 백오프+지터로 자동 재시도해 이런 일시 스파이크를 흡수한다.
    gemini_max_attempts: int = 4
    # 기본 모델이 429(무료 일일 쿼터 소진)·503(고수요) 등으로 막혔을 때 순서대로 시도할
    # 예비 모델(쉼표 구분). 무료 티어 일일 쿼터는 프로젝트×모델 버킷이라 모델마다 별도 —
    # 2026-07-15 장애: gemini-3.5-flash 20 RPD 소진으로 꼬리질문·리포트가 전부 실패.
    gemini_fallback_models: str = "gemini-flash-latest,gemini-2.5-flash-lite,gemini-2.5-flash"
    # 예비 API 키 — 반드시 **다른 GCP 프로젝트**에서 발급된 키여야 의미가 있다(쿼터는
    # 키가 아니라 프로젝트 단위). 주 키의 모든 모델이 막혔을 때만 사용된다.
    gemini_api_key_backup: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def gemini_fallback_model_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_fallback_models.split(",") if m.strip()]


settings = Settings()
