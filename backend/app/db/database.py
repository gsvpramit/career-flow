"""SQLAlchemy engine, base class, and session initialization."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def build_engine(db_path: Path) -> Engine:
    """Create a SQLite engine ensuring parent directories exist and WAL mode is active."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 60.0},
        future=True,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA synchronous=NORMAL;")
            cursor.execute("PRAGMA busy_timeout=60000;")
        finally:
            cursor.close()

    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a sessionmaker bound to the provided SQLAlchemy engine."""
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
