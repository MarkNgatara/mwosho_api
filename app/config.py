from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "Mwosho Data Cleaning App"
    DEBUG: bool = False
    FRONTEND_URL: str = "https://app.mwosho.com"

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

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRO_PRICE_MONTHLY: str = ""       # price_xxx from Stripe dashboard
    STRIPE_PRO_PRICE_YEARLY: str = ""
    STRIPE_ENTERPRISE_PRICE_MONTHLY: str = ""
    STRIPE_ENTERPRISE_PRICE_YEARLY: str = ""

    # VirusTotal
    VIRUSTOTAL_API_KEY: str = ""

    # Gmail SMTP
    GMAIL_USER: str = ""
    GMAIL_APP_PASSWORD: str = ""

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
