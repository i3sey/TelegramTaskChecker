"""Reset the PostgreSQL database, clear review locks, and recreate schema."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
import redis.asyncio as redis
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

from src.config import config
from src.db.engine import init_db


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def _get_db_settings() -> dict:
    return {
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", "postgres"),
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "database": os.getenv("POSTGRES_DB", "telegram_task_checker"),
    }


async def _clear_redis_review_state() -> None:
    """Clear Redis keys related to active reviews."""
    client = redis.from_url(
        config.redis.url,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        keys_to_delete: list[str] = []
        async for key in client.scan_iter("active_review:*"):
            keys_to_delete.append(key)
        async for key in client.scan_iter("expert_submissions:*"):
            keys_to_delete.append(key)
        keys_to_delete.append("review_lock_deadlines")

        if keys_to_delete:
            await client.delete(*keys_to_delete)
    finally:
        await client.close()

async def _reset_db() -> None:
    settings = _get_db_settings()
    db_name = settings["database"]

    conn = await asyncpg.connect(
        user=settings["user"],
        password=settings["password"],
        host=settings["host"],
        port=settings["port"],
        database="postgres",
    )
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) "
            "FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            db_name,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()

    await _clear_redis_review_state()
    await init_db()


def main() -> None:
    _load_env()
    asyncio.run(_reset_db())
    print("Database and Redis review locks reset complete.")


if __name__ == "__main__":
    main()
