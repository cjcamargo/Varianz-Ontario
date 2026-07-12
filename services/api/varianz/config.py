from dataclasses import dataclass
from os import getenv
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    environment: str = getenv("APP_ENV", "local")
    dataset_zip: Path = Path(getenv("DATASET_ZIP", "Wageningen MVP Dataset.zip"))
    openai_api_key: str | None = getenv("OPENAI_API_KEY") or None
    openai_model: str = getenv("OPENAI_MODEL", "gpt-5.6-luna")
    openai_timeout_seconds: float = float(getenv("OPENAI_TIMEOUT_SECONDS", "30"))
    openai_max_output_tokens: int = int(getenv("OPENAI_MAX_OUTPUT_TOKENS", "900"))


settings = Settings()
