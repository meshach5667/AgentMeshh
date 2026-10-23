import asyncio
import logging
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.core.config import settings

logger = logging.getLogger(__name__)

SERVER_DIR = Path(__file__).resolve().parents[2]


def _upgrade_head() -> None:
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    command.upgrade(config, "head")


async def migrate_database() -> None:
    # SQLite development databases are built by scripts/init_dev_db.py; it cannot run every migration.
    if not settings.DATABASE_URL.startswith("postgresql"):
        return
    logger.info("Applying database migrations")
    # alembic's env.py runs its own event loop, so it needs a thread of its own.
    await asyncio.to_thread(_upgrade_head)
    logger.info("Database schema is up to date")
