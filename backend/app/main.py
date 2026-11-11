"""FastAPI application factory for Project Job Mark1."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.app.api.deps import get_config_manager
from backend.app.api.routes_config import router as config_router
from backend.app.api.routes_jobs import router as jobs_router
from backend.app.api.routes_resumes import router as resumes_router
from backend.app.config import DEFAULT_DB_PATH, PROJECT_ROOT
from backend.app.db.database import Base, build_engine, build_session_factory
from backend.app.db import models as _models  # noqa: F401 - registers ORM tables
from backend.app.services.config_manager import ConfigManager


def _ensure_sqlite_columns(engine: Engine) -> None:
    """Safely add new nullable/defaulted columns when opening an existing SQLite DB."""
    migrations: list[tuple[str, str, str]] = [
        ("resumes", "role_track", "VARCHAR(64) NOT NULL DEFAULT 'senior_swe'"),
        ("job_postings", "session_id", "INTEGER REFERENCES scrape_sessions(id)"),
    ]
    with engine.begin() as conn:
        for table_name, column_name, column_ddl in migrations:
            rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
            existing_cols = {str(row[1]) for row in rows}
            if existing_cols and column_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_ddl}"))


def _ensure_v2_sqlite_columns(engine) -> None:
    """Ensure new session, job posting, and seen-job columns exist on upgraded SQLite DBs."""
    from sqlalchemy import inspect as sa_inspect, text as sa_text

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())
    alterations: list[tuple[str, str, str]] = [
        ("scrape_sessions", "posted_within", "VARCHAR(20) NOT NULL DEFAULT '24h'"),
        ("scrape_sessions", "scanned_count", "INTEGER NOT NULL DEFAULT 0"),
        ("scrape_sessions", "saved_count", "INTEGER NOT NULL DEFAULT 0"),
        ("scrape_sessions", "filtered_count", "INTEGER NOT NULL DEFAULT 0"),
        ("scrape_sessions", "filter_breakdown_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("scrape_sessions", "source_notes_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("job_postings", "url_hash", "VARCHAR(64)"),
        ("job_postings", "content_fingerprint", "VARCHAR(64)"),
        ("job_postings", "source", "VARCHAR(60) NOT NULL DEFAULT 'manual'"),
        ("job_postings", "posted_at", "DATETIME"),
        ("job_postings", "work_type", "VARCHAR(40) NOT NULL DEFAULT 'unspecified'"),
        ("job_postings", "job_type", "VARCHAR(40) NOT NULL DEFAULT 'full-time'"),
        ("job_postings", "work_auth", "VARCHAR(40) NOT NULL DEFAULT 'unspecified'"),
        ("job_postings", "disposition", "VARCHAR(40) NOT NULL DEFAULT 'kept'"),
        ("job_postings", "application_status", "VARCHAR(40) NOT NULL DEFAULT 'ready'"),
        ("job_postings", "relevance_score", "FLOAT NOT NULL DEFAULT 0.0"),
    ]
    with engine.begin() as conn:
        for table, column, col_def in alterations:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


def create_app(
    config_manager: ConfigManager | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    output_dir_override: Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application."""
    manager = config_manager or ConfigManager()
    engine = build_engine(db_path)
    session_factory = build_session_factory(engine)

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        manager.ensure_initialized()
        Base.metadata.create_all(bind=engine)
        _ensure_sqlite_columns(engine)
        _ensure_v2_sqlite_columns(engine)
        yield
        engine.dispose()

    application = FastAPI(
        title="CareerFlow",
        version="0.1.0",
        description="Job scraping, ATS match analysis, and resume tailoring studio.",
        lifespan=lifespan,
    )
    application.state.config_manager = manager
    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.output_dir_override = output_dir_override

    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get("/api/health", tags=["system"])
    def health(cfg_mgr: ConfigManager = Depends(get_config_manager)) -> dict[str, object]:
        cfg = cfg_mgr.get_config_response()
        return {
            "status": "ok",
            "needs_setup": cfg.needs_setup,
            "missing_defaults": cfg.missing_defaults,
            "role_tracks_loaded": len(cfg_mgr.list_role_tracks()),
        }

    application.include_router(config_router)
    application.include_router(resumes_router)
    application.include_router(jobs_router)

    dist_dir = PROJECT_ROOT / "frontend" / "dist"
    assets_dir = dist_dir / "assets"
    index_file = dist_dir / "index.html"
    if assets_dir.is_dir() and index_file.is_file():
        application.mount("/assets", StaticFiles(directory=str(assets_dir)), name="frontend-assets")

        @application.get("/", include_in_schema=False)
        def serve_spa_index() -> FileResponse:
            return FileResponse(str(index_file))

    return application


app = create_app()
