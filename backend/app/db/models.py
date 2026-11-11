"""Core SQLAlchemy ORM tables for scrape sessions, resumes, jobs, and tailoring runs."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ScrapeSessionRecord(Base):
    """Named job-scraping session grouping postings by run, location, and role."""

    __tablename__ = "scrape_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    posted_within: Mapped[str] = mapped_column(String(20), default="24h", nullable=False)
    scanned_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    saved_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filtered_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    filter_breakdown_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    source_notes_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ResumeRecord(Base):
    """Stores a canonical base resume or supplementary experience context."""

    __tablename__ = "resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    role_track: Mapped[str] = mapped_column(String(64), default="senior_swe", nullable=False)
    is_base: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), default="form", nullable=False)
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_json: Mapped[str] = mapped_column(Text, nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class JobPostingRecord(Base):
    """Stores scraped/pasted job postings, extracted expectations, and salary info."""

    __tablename__ = "job_postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("scrape_sessions.id"), nullable=True
    )
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    company: Mapped[str] = mapped_column(String(200), default="Unknown Company", nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="Untitled Role", nullable=False)
    role_track: Mapped[str] = mapped_column(String(64), default="senior_swe", nullable=False)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    yoe_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    yoe_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(60), default="manual", nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_type: Mapped[str] = mapped_column(String(40), default="unspecified", nullable=False)
    job_type: Mapped[str] = mapped_column(String(40), default="full-time", nullable=False)
    work_auth: Mapped[str] = mapped_column(String(40), default="unspecified", nullable=False)
    disposition: Mapped[str] = mapped_column(String(40), default="kept", nullable=False)
    application_status: Mapped[str] = mapped_column(String(40), default="ready", nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class SeenJobFingerprintRecord(Base):
    """Permanent deduplication ledger for every scraped, saved, auto-filtered, or discarded job."""

    __tablename__ = "seen_job_fingerprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    company: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    location: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    source: Mapped[str] = mapped_column(String(60), default="manual", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    disposition: Mapped[str] = mapped_column(String(40), default="saved", nullable=False)
    filter_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class TailoringRunRecord(Base):
    """Stores ATS scoring results, live diffs, and generated output folder paths."""

    __tablename__ = "tailoring_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("job_postings.id"), nullable=False)
    resume_id: Mapped[int] = mapped_column(ForeignKey("resumes.id"), nullable=False)
    base_score: Mapped[float] = mapped_column(Float, nullable=False)
    tailored_score: Mapped[float] = mapped_column(Float, nullable=False)
    report_json: Mapped[str] = mapped_column(Text, nullable=False)
    tailored_resume_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_folder: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
