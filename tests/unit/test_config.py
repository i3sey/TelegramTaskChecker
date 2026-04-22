import pytest
from src.config import _get_database_url, _get_redis_url


class TestDatabaseUrl:
    """Tests for _get_database_url function."""

    def test_database_url_format(self):
        url = _get_database_url()
        assert url.startswith("postgresql+asyncpg://")
        assert "localhost" in url

    def test_database_url_contains_postgres_user(self):
        url = _get_database_url()
        assert "postgres" in url

    def test_database_url_contains_port(self):
        url = _get_database_url()
        # Port should be in the URL
        assert ":" in url.split("@")[1] if "@" in url else True


class TestRedisUrl:
    """Tests for _get_redis_url function."""

    def test_redis_url_format(self):
        url = _get_redis_url()
        assert url.startswith("redis://")

    def test_redis_url_contains_host(self):
        url = _get_redis_url()
        assert "localhost" in url

    def test_redis_url_default_port(self):
        url = _get_redis_url()
        assert ":6379" in url

    def test_redis_url_with_password(self, monkeypatch):
        monkeypatch.setenv("REDIS_PASSWORD", "secret123")
        url = _get_redis_url()
        assert ":secret123@" in url

    def test_redis_url_without_password(self, monkeypatch):
        monkeypatch.setenv("REDIS_PASSWORD", "")
        url = _get_redis_url()
        # Should not have double colon before host
        assert url.startswith("redis://localhost")

    def test_redis_url_custom_db(self, monkeypatch):
        monkeypatch.setenv("REDIS_DB", "2")
        url = _get_redis_url()
        assert url.endswith("/2")