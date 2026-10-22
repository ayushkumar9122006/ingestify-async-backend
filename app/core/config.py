import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "Ingestify"
    PROJECT_DESCRIPTION: str = "Enterprise-Grade Asynchronous Document & Media Processing Engine"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    # PostgreSQL Database Settings
    POSTGRES_SERVER: str = os.getenv("POSTGRES_SERVER", "db")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "postgres")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "postgres")
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "ingestify")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    SQLALCHEMY_DATABASE_URI: Optional[str] = None

    @property
    def database_url(self) -> str:
        if self.SQLALCHEMY_DATABASE_URI:
            return self.SQLALCHEMY_DATABASE_URI
        # Check standard DATABASE_URL env var
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url
        return f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Celery & Redis Settings
    CELERY_BROKER_URL: str = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
    CELERY_RESULT_BACKEND: str = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0")

    # Security & JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "ingestify-production-super-secret-key-change-me-32chars")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1 day

    # Storage paths
    STORAGE_BASE_DIR: str = os.getenv("STORAGE_BASE_DIR", "/app/storage")
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "/app/storage/uploads")
    ARTIFACT_DIR: str = os.getenv("ARTIFACT_DIR", "/app/storage/artifacts")
    THUMBNAIL_DIR: str = os.getenv("THUMBNAIL_DIR", "/app/storage/thumbnails")

    # Queue Routing Parameters
    # Files smaller than 1MB are automatically routed to high-priority queue
    HIGH_PRIORITY_SIZE_THRESHOLD_BYTES: int = 1 * 1024 * 1024  # 1 MB
    MAX_FILE_SIZE_BYTES: int = 100 * 1024 * 1024  # 100 MB


settings = Settings()
