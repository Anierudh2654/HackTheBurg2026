"""SQLAlchemy engine/session helpers."""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from ..config import get_settings


def session_factory():
    url = get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is required for database-backed deployment")
    engine = create_engine(url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)
