# =============================================================================
# app/core/config.py
# Centralised settings — reads from environment / .env file at startup
# Pydantic BaseSettings validates types so bad config fails fast, not silently
# =============================================================================

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Enterprise Workflow Optimization & Document Automation Suite"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_PREFIX: str = "/api/v1"

    # ── PostgreSQL (asyncpg driver) ───────────────────────────────────────────
    POSTGRES_USER: str = "workflow_user"
    POSTGRES_PASSWORD: str = "workflow_pass"
    POSTGRES_DB: str = "workflow_db"
    POSTGRES_HOST: str = "db"          # Docker service name
    POSTGRES_PORT: int = 5432
    DB_ECHO: bool = False              # Set True locally to see raw SQL

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── LlamaIndex / OpenAI (swap key in .env — never hardcode) ──────────────
    OPENAI_API_KEY: str = "sk-placeholder"   # override in .env

    # ── CORS ─────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = ["*"]       # tighten in production

    class Config:
        env_file = ".env"
        case_sensitive = True


@lru_cache()        # singleton — settings parsed once per process lifetime
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
