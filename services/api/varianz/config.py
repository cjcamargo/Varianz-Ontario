from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field("local", validation_alias="APP_ENV")
    dataset_zip: Path = Field(PROJECT_ROOT / "Wageningen MVP Dataset.zip", validation_alias="DATASET_ZIP")
    openai_api_key: str | None = Field(None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field("gpt-5.6-luna", validation_alias="OPENAI_MODEL")
    openai_timeout_seconds: float = Field(60, validation_alias="OPENAI_TIMEOUT_SECONDS")
    openai_max_output_tokens: int = Field(0, validation_alias="OPENAI_MAX_OUTPUT_TOKENS")
    openai_reasoning_effort: str = Field("low", validation_alias="OPENAI_REASONING_EFFORT")
    supabase_url: str | None = Field(None, validation_alias="SUPABASE_URL")
    supabase_publishable_key: str | None = Field(None, validation_alias="SUPABASE_PUBLISHABLE_KEY")
    supabase_service_role_key: str | None = Field(
        None, validation_alias="SUPABASE_SERVICE_ROLE_KEY"
    )
    supabase_jwt_secret: str | None = Field(None, validation_alias="SUPABASE_JWT_SECRET")
    auth_required: bool = Field(False, validation_alias="AUTH_REQUIRED")
    cors_origins: str = Field("", validation_alias="CORS_ORIGINS")
    database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    supabase_project_ref: str | None = Field(None, validation_alias="SUPABASE_PROJECT_REF")
    data_backend: str = Field("supabase", validation_alias="DATA_BACKEND")

    @field_validator("dataset_zip", mode="after")
    @classmethod
    def resolve_dataset_zip(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def allowed_origins(self) -> list[str]:
        local = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
        ]
        configured = [origin.strip().rstrip("/") for origin in self.cors_origins.split(",") if origin.strip()]
        return list(dict.fromkeys([*local, *configured]))


settings = Settings()
