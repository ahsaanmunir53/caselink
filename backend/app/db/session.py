"""Async SQLAlchemy engine. SQLite locally, Postgres (Neon) when DATABASE_URL is set."""

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.models import Base


def sqlalchemy_url(settings: Settings) -> str:
    if settings.database_url:
        url = settings.database_url
        for prefix in ("postgresql://", "postgres://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url
    return f"sqlite+aiosqlite:///{settings.sqlite_path}"


def make_engine(settings: Settings) -> AsyncEngine:
    url = sqlalchemy_url(settings)
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        # Neon suspends idle compute; recycle connections so stale ones are not reused.
        kwargs.update(pool_size=3, max_overflow=2, pool_recycle=240)
    return create_async_engine(url, **kwargs)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
