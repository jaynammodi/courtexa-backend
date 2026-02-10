import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
    ECOURTS_BASE_URL: str = "https://services.ecourts.gov.in/ecourtindia_v6"
    SESSION_TTL: int = 900  # 15 minutes
    MAX_RETRIES: int = 3

    class Config:
        env_file = ".env"

settings = Settings()