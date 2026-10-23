import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_production_rejects_default_secret():
    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="production",
            PUBLIC_BASE_URL="https://api.example.com",
            SECRET_KEY="supersecretkey",
            _env_file=None,
        )


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValidationError):
        Settings(
            ENVIRONMENT="production",
            PUBLIC_BASE_URL="https://api.example.com",
            SECRET_KEY="x" * 40,
            CORS_ORIGINS=["*"],
            _env_file=None,
        )


def test_production_disables_test_credits():
    s = Settings(
        ENVIRONMENT="production", PUBLIC_BASE_URL="https://api.example.com", SECRET_KEY="x" * 40, _env_file=None
    )
    assert s.test_credits_enabled is False


def test_dev_allows_default_secret():
    assert Settings(ENVIRONMENT="dev", _env_file=None).is_dev


def test_heartbeat_timeout_must_cover_several_intervals():
    with pytest.raises(ValidationError, match="HEARTBEAT_TIMEOUT_SECONDS"):
        Settings(HEARTBEAT_TIMEOUT_SECONDS=15, WORKER_HEARTBEAT_INTERVAL_SECONDS=15, _env_file=None)
    Settings(HEARTBEAT_TIMEOUT_SECONDS=15, WORKER_HEARTBEAT_INTERVAL_SECONDS=3, _env_file=None)


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("postgresql://u:p@db/agentmesh", "postgresql+asyncpg://u:p@db/agentmesh"),
        ("postgres://u:p@db:5432/agentmesh?sslmode=require", "postgresql+asyncpg://u:p@db:5432/agentmesh?ssl=require"),
        ("postgresql+asyncpg://u:p@db/agentmesh", "postgresql+asyncpg://u:p@db/agentmesh"),
        ("sqlite+aiosqlite:///./dev.db", "sqlite+aiosqlite:///./dev.db"),
    ],
)
def test_database_url_uses_async_driver(given, expected):
    assert Settings(DATABASE_URL=given, _env_file=None).DATABASE_URL == expected
