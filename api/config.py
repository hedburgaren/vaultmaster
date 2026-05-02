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

    # CORS
    allowed_origins: str = ""  # comma-separated, e.g. "https://example.com,http://localhost:3100"

    # Base URL (for OAuth callbacks etc.)
    base_url: str = "https://vm.example.com"

    # Encryption
    age_public_key: str = ""

    # Credential vault — separate from JWT secret_key by design.
    # Format: "v1:<base64-Fernet-key>,v2:<base64-Fernet-key>"
    # The HIGHEST version number is used for new encryptions; all listed
    # versions are tried on decrypt (MultiFernet rotation). Generate keys
    # with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    credentials_master_keys: str = ""

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
        extra = "ignore"  # tolerate extra env vars (POSTGRES_PASSWORD, etc.)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
