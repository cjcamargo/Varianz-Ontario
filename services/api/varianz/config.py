from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = Field("local", validation_alias="APP_ENV")
    dataset_zip: Path = Field(Path("Wageningen MVP Dataset.zip"), validation_alias="DATASET_ZIP")
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


settings = Settings()
