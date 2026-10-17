from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_name: str = "telegram-autopost-saas"
    log_level: str = "INFO"

    postgres_db: str = "autopost"
    postgres_user: str = "autopost"
    postgres_password: str = "change-me"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    redis_url: str = "redis://redis:6379/0"
    bot_token: str = ""
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None

    session_encryption_key: str = ""
    
    owner_telegram_ids: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def owner_ids(self) -> set[int]:
        result: set[int] = set()
        for raw in self.owner_telegram_ids.split(","):
            raw = raw.strip()
            if raw:
                try:
                    result.add(int(raw))
                except ValueError:
                    continue
        return result


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
