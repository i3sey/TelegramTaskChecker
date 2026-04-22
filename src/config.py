"""Configuration module for TelegramTaskChecker."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_path)


@dataclass
class BotConfig:
    """Telegram bot configuration."""
    token: str
    proxy: dict | None = None  # e.g., {"http": "socks5://...", "https": "socks5://..."}


@dataclass
class DatabaseConfig:
    """Database configuration."""
    url: str
    echo: bool = False


@dataclass
class RedisConfig:
    """Redis configuration."""
    url: str


@dataclass
class SheetsConfig:
    """Google Sheets configuration."""
    spreadsheet_id: str | None
    credentials_path: str | None


@dataclass
class Config:
    """Main application configuration."""
    DEBUG: bool
    bot: BotConfig
    db: DatabaseConfig
    redis: RedisConfig
    sheets: SheetsConfig


def _get_database_url() -> str:
    """Build database URL from environment variables."""
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "postgres")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db_name = os.getenv("POSTGRES_DB", "telegram_task_checker")

    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db_name}"


def _get_redis_url() -> str:
    """Build Redis URL from environment variables."""
    host = os.getenv("REDIS_HOST", "localhost")
    port = os.getenv("REDIS_PORT", "6379")
    db = os.getenv("REDIS_DB", "0")
    password = os.getenv("REDIS_PASSWORD", "")

    if password:
        return f"redis://:{password}@{host}:{port}/{db}"
    return f"redis://{host}:{port}/{db}"


# Global configuration instance
config = Config(
    DEBUG=os.getenv("DEBUG", "false").lower() in ("true", "1", "yes"),
    bot=BotConfig(
        token=os.getenv("BOT_TOKEN", ""),
        proxy={
            "http": os.getenv("HTTP_PROXY"),
            "https": os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY"),
        },
    ),
    db=DatabaseConfig(
        url=_get_database_url(),
        echo=os.getenv("DB_ECHO", "false").lower() in ("true", "1", "yes"),
    ),
    redis=RedisConfig(
        url=_get_redis_url(),
    ),
    sheets=SheetsConfig(
        spreadsheet_id=os.getenv("GOOGLE_SHEETS_ID") or None,
        credentials_path=os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE") or None,
    ),
)