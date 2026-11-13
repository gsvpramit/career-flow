"""FastAPI application factory for Project Job Mark1."""

from __future__ import annotations

import base64
import binascii
import os
import secrets
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
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
from backend.app.services.batch_scraper import ScrapeProgressStore
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
        ("job_postings", "applied_at", "DATETIME"),
        ("job_postings", "application_notes", "TEXT NOT NULL DEFAULT ''"),
        ("job_postings", "relevance_score", "FLOAT NOT NULL DEFAULT 0.0"),
        ("session_filtered_jobs", "filter_reasons_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("session_filtered_jobs", "suitability_details_json", "TEXT NOT NULL DEFAULT '[]'"),
    ]
    with engine.begin() as conn:
        for table, column, col_def in alterations:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(sa_text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Robots-Tag": "noindex, nofollow",
}


class _AuthRateLimiter:
    """In-memory sliding-window lockout limiter against repeated failed Basic Auth attempts."""

    def __init__(self, max_failures: int = 8, window_seconds: int = 300) -> None:
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._failures: dict[str, deque[float]] = {}

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._failures.get(key)
        if q is None:
            return deque()
        cutoff = now - self.window_seconds
        while q and q[0] < cutoff:
            q.popleft()
        if not q:
            self._failures.pop(key, None)
        return q

    def retry_after(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) >= self.max_failures:
                remaining = int(self.window_seconds - (now - q[0]))
                return max(1, remaining)
            return 0

    def record_failure(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            if len(self._failures) >= 2048 and key not in self._failures:
                oldest_key = next(iter(self._failures))
                self._failures.pop(oldest_key, None)
            q = self._prune(key, now)
            if not q:
                q = deque()
                self._failures[key] = q
            q.append(now)
            if len(q) >= self.max_failures:
                remaining = int(self.window_seconds - (now - q[0]))
                return max(1, remaining)
            return 0

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


def _client_ip(request: Request) -> str:
    cf_ip = (request.headers.get("cf-connecting-ip") or "").strip()
    if cf_ip:
        return cf_ip
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        return xff.split(",")[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _is_basic_authorized(auth_header: str | None, expected_user: str, expected_pass: str) -> bool:
    if not auth_header:
        return False
    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "basic" or not token.strip():
        return False
    try:
        decoded = base64.b64decode(token.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    user, password = decoded.split(":", 1)
    user_ok = secrets.compare_digest(user.encode("utf-8"), expected_user.encode("utf-8"))
    pass_ok = secrets.compare_digest(password.encode("utf-8"), expected_pass.encode("utf-8"))
    return user_ok and pass_ok


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
    application.state.scrape_progress = ScrapeProgressStore()

    extra_origins = [
        o.strip()
        for o in os.getenv("CAREERFLOW_ALLOWED_ORIGINS", "").split(",")
        if o.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            *extra_origins,
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    auth_pass = os.getenv("CAREERFLOW_BASIC_AUTH_PASS", "").strip()
    auth_user = os.getenv("CAREERFLOW_BASIC_AUTH_USER", "").strip() or "careerflow"
    max_auth_failures = max(3, int(os.getenv("CAREERFLOW_AUTH_MAX_FAILURES", "8") or "8"))
    rate_limiter = _AuthRateLimiter(max_failures=max_auth_failures, window_seconds=300)

    @application.middleware("http")
    async def security_and_auth_middleware(request: Request, call_next) -> Response:
        if auth_pass:
            client_key = _client_ip(request)
            auth_header = request.headers.get("authorization")
            wait_sec = rate_limiter.retry_after(client_key)
            if wait_sec > 0 and request.url.path != "/api/health":
                return Response(
                    content="Too many failed login attempts. Retry later.",
                    status_code=429,
                    headers={
                        "Retry-After": str(wait_sec),
                        **_SECURITY_HEADERS,
                    },
                )
            authorized = _is_basic_authorized(auth_header, auth_user, auth_pass)
            if not authorized:
                if request.url.path == "/api/health":
                    return JSONResponse({"status": "ok"}, headers=_SECURITY_HEADERS)
                if auth_header:
                    locked_sec = rate_limiter.record_failure(client_key)
                    if locked_sec > 0:
                        return Response(
                            content="Too many failed login attempts. Retry later.",
                            status_code=429,
                            headers={
                                "Retry-After": str(locked_sec),
                                **_SECURITY_HEADERS,
                            },
                        )
                return Response(
                    content="Authentication required.",
                    status_code=401,
                    headers={
                        "WWW-Authenticate": 'Basic realm="CareerFlow Studio"',
                        **_SECURITY_HEADERS,
                    },
                )
            rate_limiter.clear(client_key)
        response = await call_next(request)
        for header_name, header_val in _SECURITY_HEADERS.items():
            response.headers.setdefault(header_name, header_val)
        return response

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
