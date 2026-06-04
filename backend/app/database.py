from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from pgvector.asyncpg import register_vector
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, connect_args={'init': register_vector})

AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session