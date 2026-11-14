from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    frontend_origin: str = "http://localhost:5173"
    database_url: str = (
        "postgresql+psycopg://document_intelligence:document_intelligence"
        "@localhost:5432/document_intelligence"
    )
    redis_url: str = "redis://localhost:6379/0"
    upload_dir: Path = Path("uploads")
    max_upload_bytes: int = 25 * 1024 * 1024
    max_pdf_pages: int = 1000
    llm_api_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    embedding_api_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = ""
    tesseract_cmd: str = "tesseract"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
