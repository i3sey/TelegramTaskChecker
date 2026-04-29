"""Reset the PostgreSQL database and recreate schema."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(PROJECT_ROOT))

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

    await init_db()


def main() -> None:
    _load_env()
    asyncio.run(_reset_db())
    print("Database reset complete.")


if __name__ == "__main__":
    main()
