from app.core import migrations


async def test_postgres_is_migrated_on_startup(monkeypatch):
    calls = []
    monkeypatch.setattr(migrations.settings, "DATABASE_URL", "postgresql+asyncpg://u:p@db/agentmesh")
    monkeypatch.setattr(migrations, "_upgrade_head", lambda: calls.append("head"))
    await migrations.migrate_database()
    assert calls == ["head"]


async def test_sqlite_is_left_to_init_dev_db(monkeypatch):
    calls = []
    monkeypatch.setattr(migrations.settings, "DATABASE_URL", "sqlite+aiosqlite:///./dev.db")
    monkeypatch.setattr(migrations, "_upgrade_head", lambda: calls.append("head"))
    await migrations.migrate_database()
    assert calls == []
