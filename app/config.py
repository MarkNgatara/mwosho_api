from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    APP_NAME: str = "1ndependence Data Cleaner"
    DEBUG: bool = False

    DB_HOST: str = "localhost"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "1ndependence"

    REDIS_URL: str = "redis://localhost:6379/0"

    SECRET_KEY: str = "change-this-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    UPLOAD_DIR: str = "storage/uploads"
    CHUNKS_DIR: str = "storage/chunks"
    PROCESSED_DIR: str = "storage/processed"
    MAX_FILE_SIZE_MB: int = 2048
    CHUNK_SIZE_ROWS: int = 100_000

    ANTHROPIC_API_KEY: str = ""
    WORKER_CONCURRENCY: int = 4

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"mysql+pymysql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
