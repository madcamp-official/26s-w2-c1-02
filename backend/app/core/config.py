from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """앱 설정. 환경변수/.env 에서 로드."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Rehearsal.io API"

    # 쉼표로 구분된 CORS 오리진. 개발 편의를 위해 localhost 전체 허용이 기본.
    cors_origins: str = "http://localhost:*,http://127.0.0.1:*"

    # PostgreSQL 접속 URL (.env의 DATABASE_URL). 미설정 시 로컬 개발 기본값.
    database_url: str = "postgresql+psycopg://rehearsal:rehearsal123@localhost:5432/rehearsal_dev"

    # LLM 제공자 선택 (mock | gemini)
    llm_provider: str = "mock"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
