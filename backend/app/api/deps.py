"""FastAPI dependency providers for ConfigManager and database sessions."""

from __future__ import annotations

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session

from backend.app.services.config_manager import ConfigManager


def get_config_manager(request: Request) -> ConfigManager:
    """Return the application's ConfigManager instance."""
    return request.app.state.config_manager


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield a transactional SQLAlchemy Session scoped to the HTTP request."""
    session_factory = request.app.state.session_factory
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
