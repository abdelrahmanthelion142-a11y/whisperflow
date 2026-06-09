from sqlalchemy.pool import NullPool
from app.core.config import settings
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

engine = create_async_engine(
    settings.POSTGRES_URL.get_secret_value(), poolclass=NullPool, echo=False #type:ignore
)
AsyncSessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)
