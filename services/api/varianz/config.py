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
    openai_timeout_seconds: float = Field(30, validation_alias="OPENAI_TIMEOUT_SECONDS")
    openai_max_output_tokens: int = Field(900, validation_alias="OPENAI_MAX_OUTPUT_TOKENS")
    supabase_url: str | None = Field(None, validation_alias="SUPABASE_URL")
    supabase_publishable_key: str | None = Field(None, validation_alias="SUPABASE_PUBLISHABLE_KEY")
    supabase_service_role_key: str | None = Field(
        None, validation_alias="SUPABASE_SERVICE_ROLE_KEY"
    )
    database_url: str | None = Field(None, validation_alias="DATABASE_URL")
    supabase_project_ref: str | None = Field(None, validation_alias="SUPABASE_PROJECT_REF")
    data_backend: str = Field("auto", validation_alias="DATA_BACKEND")

    @field_validator("dataset_zip", mode="after")
    @classmethod
    def resolve_dataset_zip(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_ROOT / value


settings = Settings()
