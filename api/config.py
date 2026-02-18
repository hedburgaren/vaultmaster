from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://vaultmaster:changeme@db:5432/vaultmaster"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # JWT
    secret_key: str = "change-this-to-a-random-secret-key"
    access_token_expire_minutes: int = 1440
    algorithm: str = "HS256"

    # Encryption
    age_public_key: str = ""

    # Notifications
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    slack_webhook_url: str = ""
    ntfy_url: str = ""
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    return Settings()
