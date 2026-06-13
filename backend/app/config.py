import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    DATABASE_URL: str = "postgresql+asyncpg://postgres:password@localhost:5432/aura_db"
    REDIS_URL: str = "redis://localhost:6379/0"
    MOCK_MODE: bool = True
    
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o"
    NEWS_API_KEY: Optional[str] = None
    TAVILY_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None

settings = Settings()
