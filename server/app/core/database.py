from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.SQL_ECHO)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Session factory used outside request dependencies (background jobs, streaming responses that outlive the
# request's dependency scope). Tests replace it via set_session_factory.
_session_factory: async_sessionmaker = AsyncSessionLocal


def set_session_factory(factory: async_sessionmaker) -> None:
    global _session_factory
    _session_factory = factory


@asynccontextmanager
async def session_scope():
    async with _session_factory() as session:
        yield session


async def get_db():
    async with _session_factory() as session:
        yield session
