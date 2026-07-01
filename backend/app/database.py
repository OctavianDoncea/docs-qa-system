import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pgvector.asyncpg import register_vector
from app.config import get_settings

settings = get_settings()


def _build_engine(url: str):
    connect_args: dict = {"init": register_vector}

    if "sslmode=require" in url:
        url = url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        connect_args["ssl"] = ssl.create_default_context()

    return create_async_engine(url, echo=False, connect_args=connect_args)


engine = _build_engine(settings.database_url)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
