"""SQLAlchemy engine and session factory.

DATABASE_URL decides the backend: sqlite:///./finaudit.db today,
postgresql+psycopg2://user:pass@host/db later — nothing else changes.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# SQLite forbids cross-thread connection sharing by default; FastAPI serves
# requests from a threadpool, so relax that for SQLite only.
connect_args = (
    {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
)

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()


def get_db():
    """FastAPI dependency: one DB session per request, always closed after."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
