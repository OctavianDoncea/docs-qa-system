import ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pgvector.asyncpg import register_vector
from app.config import get_settings

settings = get_settings()


def normalize_db_url(url: str) -> tuple[str, dict]:
    connect_args: dict = {}

    if "sslmode=require" in url:
        url = url.replace("?sslmode=require", "").replace("&sslmode=require", "")
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
        connect_args["ssl"] = ssl_ctx

    return url, connect_args


def _build_engine(url: str):
    url, connect_args = normalize_db_url(url)
    connect_args["init"] = register_vector
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
