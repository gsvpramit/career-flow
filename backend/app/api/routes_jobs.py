"""Endpoints for job scraping, weighted analysis, ATS scoring, and multi-format export."""

from __future__ import annotations

import io
import json
import os
import shutil
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from backend.app.api.deps import get_config_manager, get_db_session
from backend.app.config import PROJECT_ROOT
from backend.app.db.models import (
    JobPostingRecord,
    ResumeRecord,
    ScrapeSessionRecord,
    SeenJobFingerprintRecord,
    SessionFilteredJobRecord,
    TailoringRunRecord,
)
from backend.app.schemas.job import (
    AnalyticsReportResponse,
    ATSReport,
    ATSScoreRequest,
    BulkExportJobItem,
    BulkExportRequest,
    BulkExportResponse,
    DraftScoreRequest,
    ExportRequest,
    ExportResponse,
    FlushDataRequest,
    FlushDataResult,
    HumanizeResumeRequest,
    HumanizeResumeResponse,
    JobAnalysis,
    JobIngestRequest,
    JobPatchRequest,
    JobPostingResponse,
    PromoteFilteredJobsRequest,
    PromoteJobsResult,
    RestoreDiscardedJobsRequest,
    ScrapeBatchRequest,
    ScrapeBatchResult,
    ScrapeProgressResponse,
    ScrapeSessionCreateRequest,
    ScrapeSessionLocationCount,
    ScrapeSessionRoleCount,
    ScrapeSessionSummary,
    SessionFilteredJobResponse,
    SessionSkillsGapResponse,
    SkillsGraphResponse,
    TailorPreviewRequest,
    TailorPreviewResponse,
    TailorSectionRequest,
    TailorSectionResponse,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.batch_scraper import (
    ScrapeProgressStore,
    canonicalize_url,
    compute_initial_relevance,
    format_filter_reason_label,
    hash_url,
    make_content_fingerprint,
    record_seen_job,
    run_batch_scrape,
)
from backend.app.services.config_manager import ConfigManager
from backend.app.services.excel_report import build_sessions_excel_workbook
from backend.app.services.exporter import export_run_artifacts
from backend.app.services.jd_analyzer import analyze_job_posting, infer_header_metadata
from backend.app.services.llm_tailor import tailor_resume_section_with_prompt
from backend.app.services.reports import build_analytics_summary, build_session_skills_gap
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.scraper import DEFAULT_HEADERS, ScrapeError, fetch_job_posting
from backend.app.services.skill_enrichment import enrich_job_weighted_skills
from backend.app.services.skills_graph import build_skills_graph
from backend.app.services.tailor import build_tailor_preview
from backend.app.services.timezone_utils import eastern_today_str, now_eastern, to_eastern

router = APIRouter(prefix="/api", tags=["jobs-and-export"])

ALLOWED_DOWNLOAD_SUFFIXES = {".pdf", ".docx", ".json", ".html"}


def _job_to_response(row: JobPostingRecord) -> JobPostingResponse:
    analysis = JobAnalysis.model_validate_json(row.analysis_json)
    if row.raw_text:
        analysis = analysis.model_copy(
            update={"weighted_skills": enrich_job_weighted_skills(row.raw_text, analysis.weighted_skills)}
        )
    return JobPostingResponse(
        id=row.id,
        session_id=row.session_id,
        url=row.url,
        analysis=analysis,
        raw_text=row.raw_text,
        source=row.source or "manual",
        posted_at=to_eastern(row.posted_at),
        work_type=row.work_type or "unspecified",
        job_type=row.job_type or "full-time",
        work_auth=row.work_auth or "unspecified",
        disposition=row.disposition or "kept",
        application_status=row.application_status or "ready",
        applied_at=to_eastern(row.applied_at),
        application_notes=row.application_notes or "",
        relevance_score=float(row.relevance_score or 0.0),
        created_at=to_eastern(row.created_at) or now_eastern(),
    )


def _resolve_resume_record(
    db: Session,
    resume_id: int | None,
    preferred_role_track: str | None = None,
) -> ResumeRecord:
    if resume_id is not None:
        record = db.get(ResumeRecord, resume_id)
        if record is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found.")
        return record

    if preferred_role_track:
        matching_base = db.scalars(
            select(ResumeRecord)
            .where(
                ResumeRecord.is_base.is_(True),
                ResumeRecord.role_track == preferred_role_track,
            )
            .order_by(ResumeRecord.id.desc())
        ).first()
        if matching_base is not None:
            return matching_base

    base_record = db.scalars(
        select(ResumeRecord).where(ResumeRecord.is_base.is_(True)).order_by(ResumeRecord.id.desc())
    ).first()
    if base_record is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="NO_BASE_RESUME: Upload a base resume or build one in the UI before scoring.",
        )
    return base_record


def _resolve_output_root(request: Request, settings_output_dir: str) -> Path:
    override: Path | None = getattr(request.app.state, "output_dir_override", None)
    if override is not None:
        return override
    env_output = os.getenv("CAREERFLOW_OUTPUT_DIR", "").strip()
    if env_output and Path(settings_output_dir) == Path("output"):
        return Path(env_output)
    candidate = Path(settings_output_dir)
    return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)


def _get_progress_store(request: Request) -> ScrapeProgressStore:
    store = getattr(request.app.state, "scrape_progress", None)
    if store is None:
        store = ScrapeProgressStore()
        request.app.state.scrape_progress = store
    return store


def _build_session_summary(db: Session, session_row: ScrapeSessionRecord) -> ScrapeSessionSummary:
    all_jobs = db.scalars(
        select(JobPostingRecord)
        .where(JobPostingRecord.session_id == session_row.id)
        .order_by(JobPostingRecord.id.desc())
    ).all()

    kept_jobs = [j for j in all_jobs if j.disposition != "discarded"]
    discarded_count = len(all_jobs) - len(kept_jobs)

    location_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    sources_used: list[str] = []
    currencies: list[str] = []

    for job in kept_jobs:
        loc_label = (job.location or "").strip() or "Unspecified"
        location_counts[loc_label] += 1
        role_counts[job.role_track or "senior_swe"] += 1
        status_counts[job.application_status or "ready"] += 1
        src_root = (job.source or "manual").split(":", 1)[0]
        if src_root and src_root not in sources_used:
            sources_used.append(src_root)
        curr = (job.salary_currency or "").strip().upper()
        if curr and curr not in currencies:
            currencies.append(curr)

    locations = [
        ScrapeSessionLocationCount(location=loc, count=count)
        for loc, count in sorted(location_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    roles = [
        ScrapeSessionRoleCount(role_track=role_id, count=count)
        for role_id, count in sorted(role_counts.items(), key=lambda pair: (-pair[1], pair[0]))
    ]

    filter_breakdown = json.loads(session_row.filter_breakdown_json or "{}")
    seen_skipped_count = sum(
        int(count)
        for reason, count in filter_breakdown.items()
        if reason == "duplicate_in_batch" or reason == "already_seen" or reason.startswith("seen:")
    )

    return ScrapeSessionSummary(
        id=session_row.id,
        name=session_row.name,
        total_jobs=len(kept_jobs),
        posted_within=session_row.posted_within or "24h",
        scanned_count=int(session_row.scanned_count or 0),
        saved_count=int(session_row.saved_count or 0),
        filtered_count=int(session_row.filtered_count or 0),
        seen_skipped_count=seen_skipped_count,
        discarded_count=discarded_count,
        filter_breakdown=filter_breakdown,
        source_notes=json.loads(session_row.source_notes_json or "[]"),
        locations=locations,
        roles=roles,
        currencies=currencies,
        status_counts=dict(status_counts),
        sources_used=sources_used,
        created_at=to_eastern(session_row.created_at) or now_eastern(),
    )


def _default_session_name(db: Session) -> str:
    existing_count = len(db.scalars(select(ScrapeSessionRecord.id)).all())
    today = eastern_today_str()
    return f"Session {existing_count + 1} ({today})"


@router.get("/sessions", response_model=list[ScrapeSessionSummary])
def list_sessions(db: Session = Depends(get_db_session)) -> list[ScrapeSessionSummary]:
    """List scrape sessions newest first with location, role, and currency breakdown."""
    sessions = db.scalars(select(ScrapeSessionRecord).order_by(ScrapeSessionRecord.id.desc())).all()
    return [_build_session_summary(db, row) for row in sessions]


@router.post("/sessions", response_model=ScrapeSessionSummary, status_code=status.HTTP_201_CREATED)
def create_session(
    payload: ScrapeSessionCreateRequest,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> ScrapeSessionSummary:
    """Create a named job-scraping session."""
    name = (payload.name or "").strip() or _default_session_name(db)
    posted_within = payload.posted_within or manager.get_settings().posted_within_default or "24h"
    row = ScrapeSessionRecord(name=name, posted_within=posted_within)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _build_session_summary(db, row)


@router.post("/sessions/{session_id}/scrape", response_model=ScrapeBatchResult)
def batch_scrape_session(
    session_id: int,
    payload: ScrapeBatchRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> ScrapeBatchResult:
    """Scrape configured boards/sources for a session with simultaneous inline filtering."""
    session_row = db.get(ScrapeSessionRecord, session_id)
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    client_override = getattr(request.app.state, "scrape_http_client", None)
    return run_batch_scrape(
        db=db,
        session_rec=session_row,
        req=payload,
        config_manager=manager,
        client=client_override,
    )


@router.post("/sessions/{session_id}/scrape/start", response_model=ScrapeProgressResponse)
def start_batch_scrape_async(
    session_id: int,
    payload: ScrapeBatchRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> ScrapeProgressResponse:
    """Start batch scraping in a background thread with real-time progress tracking."""
    session_row = db.get(ScrapeSessionRecord, session_id)
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    session_factory = request.app.state.session_factory
    client_override = getattr(request.app.state, "scrape_http_client", None)
    store = _get_progress_store(request)
    return store.start(
        session_id=session_id,
        session_factory=session_factory,
        config_manager=manager,
        req=payload,
        client_override=client_override,
    )


@router.get("/sessions/{session_id}/scrape/progress", response_model=ScrapeProgressResponse)
def get_batch_scrape_progress(
    session_id: int,
    request: Request,
) -> ScrapeProgressResponse:
    """Poll live scraping progress and inline filter counters for a session."""
    return _get_progress_store(request).get(session_id)


@router.post("/sessions/{session_id}/scrape/stop", response_model=ScrapeProgressResponse)
def stop_batch_scrape(
    session_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
) -> ScrapeProgressResponse:
    """Request early cooperative stop of an active batch scrape while keeping collected results."""
    if db.get(ScrapeSessionRecord, session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")
    return _get_progress_store(request).cancel(session_id)


@router.get("/sessions/{session_id}/filtered", response_model=list[SessionFilteredJobResponse])
def list_session_filtered_jobs(
    session_id: int,
    category: str | None = None,
    db: Session = Depends(get_db_session),
) -> list[SessionFilteredJobResponse]:
    """List rule-filtered and seen/skipped postings recorded during scrapes for a session."""
    if db.get(ScrapeSessionRecord, session_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    stmt = select(SessionFilteredJobRecord).where(SessionFilteredJobRecord.session_id == session_id)
    if category in ("auto_filtered", "seen_skipped"):
        stmt = stmt.where(SessionFilteredJobRecord.category == category)
    rows = db.scalars(stmt.order_by(SessionFilteredJobRecord.id.desc())).all()
    results: list[SessionFilteredJobResponse] = []
    for row in rows:
        try:
            all_reasons = [str(x) for x in json.loads(row.filter_reasons_json or "[]") if x]
        except ValueError:
            all_reasons = []
        if not all_reasons and row.filter_reason:
            all_reasons = [row.filter_reason]
        try:
            notes = [str(x) for x in json.loads(row.suitability_details_json or "[]") if x]
        except ValueError:
            notes = []
        results.append(
            SessionFilteredJobResponse(
                id=row.id,
                session_id=row.session_id,
                url=row.url,
                url_hash=row.url_hash,
                title=row.title,
                company=row.company,
                source=row.source,
                location=row.location,
                role_track=row.role_track,
                category="seen_skipped" if row.category == "seen_skipped" else "auto_filtered",
                filter_reason=row.filter_reason,
                reason_label=format_filter_reason_label(row.filter_reason),
                filter_reasons=all_reasons,
                reason_labels=[format_filter_reason_label(r) for r in all_reasons],
                suitability_notes=notes,
                posted_at=to_eastern(row.posted_at),
                raw_text_preview=(row.raw_text or "")[:600],
                promoted_job_id=row.promoted_job_id,
                created_at=to_eastern(row.created_at) or now_eastern(),
            )
        )
    return results


@router.post("/sessions/{session_id}/filtered/promote", response_model=PromoteJobsResult)
def promote_filtered_jobs(
    session_id: int,
    payload: PromoteFilteredJobsRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    manager: ConfigManager = Depends(get_config_manager),
) -> PromoteJobsResult:
    """Promote selected filtered or seen/skipped jobs into the session's active Saved Jobs list."""
    session_row = db.get(ScrapeSessionRecord, session_id)
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    filtered_rows = db.scalars(
        select(SessionFilteredJobRecord)
        .where(
            SessionFilteredJobRecord.session_id == session_id,
            SessionFilteredJobRecord.id.in_(payload.filtered_ids),
        )
        .order_by(SessionFilteredJobRecord.id.asc())
    ).all()
    if not filtered_rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching filtered postings found.")

    settings = manager.get_settings()
    client_override: httpx.Client | None = getattr(request.app.state, "scrape_http_client", None)
    owns_client = False
    http_client: httpx.Client | None = client_override

    added_count = 0
    already_saved_count = 0
    failed_count = 0
    saved_jobs: list[JobPostingResponse] = []

    try:
        for frow in filtered_rows:
            canon_u = canonicalize_url(frow.url)
            u_hash = frow.url_hash or hash_url(canon_u) or hash_url(frow.url)
            fp = make_content_fingerprint(frow.company, frow.title, frow.location)

            # Check if this posting already exists inside this session
            existing_in_session = db.scalars(
                select(JobPostingRecord).where(
                    JobPostingRecord.session_id == session_id,
                    JobPostingRecord.url_hash == u_hash,
                )
            ).first()
            if existing_in_session is None:
                existing_in_session = db.scalars(
                    select(JobPostingRecord).where(
                        JobPostingRecord.session_id == session_id,
                        JobPostingRecord.content_fingerprint == fp,
                    )
                ).first()

            if existing_in_session is not None:
                if existing_in_session.disposition == "kept":
                    already_saved_count += 1
                    frow.promoted_job_id = existing_in_session.id
                    continue
                existing_in_session.disposition = "kept"
                if payload.role_track_override:
                    existing_in_session.role_track = payload.role_track_override
                frow.promoted_job_id = existing_in_session.id
                record_seen_job(
                    db,
                    url=canon_u or frow.url,
                    url_hash=u_hash,
                    content_fingerprint=fp,
                    company=existing_in_session.company,
                    title=existing_in_session.title,
                    location=existing_in_session.location,
                    source=existing_in_session.source,
                    disposition="saved",
                    filter_reason=None,
                    session_id=session_id,
                )
                added_count += 1
                saved_jobs.append(_job_to_response(existing_in_session))
                continue

            # Resolve full JD text: 1) stored filtered raw_text, 2) prior session JobPostingRecord, 3) URL fetch, 4) summary fallback
            raw_text = (frow.raw_text or "").strip()
            if not raw_text:
                prior_job = db.scalars(
                    select(JobPostingRecord)
                    .where(JobPostingRecord.url_hash == u_hash)
                    .order_by(JobPostingRecord.id.desc())
                ).first()
                if prior_job and (prior_job.raw_text or "").strip():
                    raw_text = prior_job.raw_text
            if not raw_text and frow.url:
                if http_client is None:
                    http_client = httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=12.0)
                    owns_client = True
                try:
                    scraped = fetch_job_posting(url=frow.url, client=http_client)
                    if (scraped.raw_text or "").strip():
                        raw_text = scraped.raw_text
                except Exception:
                    pass
            if not raw_text:
                raw_text = "\n".join(
                    part
                    for part in [
                        f"{frow.title} at {frow.company}",
                        f"Location: {frow.location}" if frow.location else "",
                        f"Source: {frow.source}",
                        f"Original Filter Reason: {frow.filter_reason}",
                        f"Apply Link: {frow.url}" if frow.url else "",
                    ]
                    if part
                )

            if not raw_text.strip():
                failed_count += 1
                continue

            track_id = payload.role_track_override or frow.role_track or manager.infer_role_track_for_title(
                frow.title, preferred_ids=settings.target_role_tracks
            )
            role_track = manager.get_role_track(track_id)
            analysis = analyze_job_posting(
                raw_text=raw_text,
                role_track=role_track,
                settings=settings,
                scraped_title=frow.title,
                scraped_company=frow.company,
                scraped_location=frow.location or None,
            )
            rel_score = compute_initial_relevance(db, analysis, settings, manager)

            job_rec = JobPostingRecord(
                session_id=session_id,
                url=canon_u or frow.url,
                company=analysis.company,
                title=analysis.title,
                location=analysis.location,
                role_track=analysis.role_track,
                salary_min=analysis.salary.min_amount,
                salary_max=analysis.salary.max_amount,
                salary_currency=analysis.salary.currency,
                yoe_min=analysis.yoe.min_years,
                yoe_max=analysis.yoe.max_years,
                raw_text=raw_text,
                analysis_json=json.dumps(analysis.model_dump(mode="json")),
                url_hash=u_hash,
                content_fingerprint=fp,
                source=frow.source,
                posted_at=frow.posted_at,
                work_type=analysis.work_type,
                job_type=analysis.job_type,
                work_auth=analysis.work_auth,
                disposition="kept",
                application_status="ready",
                relevance_score=rel_score,
            )
            db.add(job_rec)
            db.flush()
            frow.promoted_job_id = job_rec.id
            frow.raw_text = raw_text
            record_seen_job(
                db,
                url=canon_u or frow.url,
                url_hash=u_hash,
                content_fingerprint=fp,
                company=analysis.company,
                title=analysis.title,
                location=analysis.location,
                source=frow.source,
                disposition="saved",
                filter_reason=None,
                session_id=session_id,
            )
            added_count += 1
            session_row.saved_count += 1
            saved_jobs.append(_job_to_response(job_rec))

        db.commit()
    finally:
        if owns_client and http_client is not None:
            http_client.close()

    return PromoteJobsResult(
        session_id=session_id,
        added_count=added_count,
        already_saved_count=already_saved_count,
        failed_count=failed_count,
        saved_jobs=saved_jobs,
    )


@router.post("/sessions/{session_id}/discarded/restore", response_model=PromoteJobsResult)
def restore_discarded_jobs(
    session_id: int,
    payload: RestoreDiscardedJobsRequest,
    db: Session = Depends(get_db_session),
) -> PromoteJobsResult:
    """Restore selected discarded jobs in a session back to Kept/Saved status."""
    session_row = db.get(ScrapeSessionRecord, session_id)
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    rows = db.scalars(
        select(JobPostingRecord).where(
            JobPostingRecord.session_id == session_id,
            JobPostingRecord.id.in_(payload.job_ids),
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching discarded jobs found.")

    added_count = 0
    already_saved_count = 0
    saved_jobs: list[JobPostingResponse] = []
    for row in rows:
        if row.disposition == "kept":
            already_saved_count += 1
            continue
        row.disposition = "kept"
        fp = row.content_fingerprint or make_content_fingerprint(row.company, row.title, row.location)
        u_hash = row.url_hash or hash_url(row.url)
        record_seen_job(
            db,
            url=row.url,
            url_hash=u_hash,
            content_fingerprint=fp,
            company=row.company,
            title=row.title,
            location=row.location,
            source=row.source,
            disposition="saved",
            filter_reason=None,
            session_id=session_id,
        )
        added_count += 1
        saved_jobs.append(_job_to_response(row))

    db.commit()
    return PromoteJobsResult(
        session_id=session_id,
        added_count=added_count,
        already_saved_count=already_saved_count,
        failed_count=0,
        saved_jobs=saved_jobs,
    )


@router.get("/jobs", response_model=list[JobPostingResponse])
def list_jobs(
    session_id: int | None = None,
    include_discarded: bool = False,
    db: Session = Depends(get_db_session),
) -> list[JobPostingResponse]:
    """List analyzed job postings newest first, optionally filtered by session."""
    stmt = select(JobPostingRecord)
    if session_id is not None:
        stmt = stmt.where(JobPostingRecord.session_id == session_id)
    if not include_discarded:
        stmt = stmt.where(JobPostingRecord.disposition != "discarded")
    rows = db.scalars(stmt.order_by(JobPostingRecord.id.desc())).all()
    return [_job_to_response(row) for row in rows]


@router.patch("/jobs/{job_id}", response_model=JobPostingResponse)
def patch_job(
    job_id: int,
    payload: JobPatchRequest,
    db: Session = Depends(get_db_session),
) -> JobPostingResponse:
    """Keep/Discard a job (persisting discard permanently) or update application status."""
    row = db.get(JobPostingRecord, job_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found.")

    if payload.disposition is not None:
        row.disposition = payload.disposition
        fp = row.content_fingerprint or make_content_fingerprint(row.company, row.title, row.location)
        u_hash = row.url_hash or hash_url(row.url)
        row.content_fingerprint = fp
        row.url_hash = u_hash
        record_seen_job(
            db,
            url=row.url,
            url_hash=u_hash,
            content_fingerprint=fp,
            company=row.company,
            title=row.title,
            location=row.location,
            source=row.source or "manual",
            disposition="discarded" if payload.disposition == "discarded" else "saved",
            filter_reason="user_discarded" if payload.disposition == "discarded" else None,
            session_id=row.session_id,
        )

    if payload.application_status is not None:
        row.application_status = payload.application_status
        if payload.application_status in ("applied", "screening", "interviewing", "offer") and row.applied_at is None:
            row.applied_at = datetime.now(timezone.utc)
        elif payload.application_status in ("ready", "resume_created"):
            row.applied_at = None

    if payload.application_notes is not None:
        row.application_notes = payload.application_notes.strip()

    db.commit()
    db.refresh(row)
    return _job_to_response(row)


@router.post("/jobs/ingest", response_model=JobPostingResponse, status_code=status.HTTP_201_CREATED)
def ingest_job(
    payload: JobIngestRequest,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> JobPostingResponse:
    """Scrape a job URL or analyze pasted JD text inside a scrape session."""
    if payload.session_id is not None:
        session_row = db.get(ScrapeSessionRecord, payload.session_id)
        if session_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")
    else:
        session_row = db.scalars(select(ScrapeSessionRecord).order_by(ScrapeSessionRecord.id.desc())).first()
        if session_row is None:
            session_row = ScrapeSessionRecord(name=_default_session_name(db))
            db.add(session_row)
            db.flush()

    try:
        scraped = fetch_job_posting(url=payload.url, raw_text=payload.raw_text)
    except ScrapeError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    settings = manager.get_settings()
    _, inferred_title = infer_header_metadata(
        scraped.raw_text,
        scraped.title,
        scraped.company,
        payload.company_override,
        payload.title_override,
    )
    track_id = payload.role_track or manager.infer_role_track_for_title(
        inferred_title,
        preferred_ids=settings.target_role_tracks,
    )
    try:
        role_track = manager.get_role_track(track_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    analysis = analyze_job_posting(
        raw_text=scraped.raw_text,
        role_track=role_track,
        settings=settings,
        scraped_title=scraped.title,
        scraped_company=scraped.company,
        scraped_location=scraped.location,
        company_override=payload.company_override,
        title_override=payload.title_override,
        location_override=payload.location_override,
    )

    canon_url = canonicalize_url(scraped.url)
    u_hash = hash_url(canon_url)
    fp = make_content_fingerprint(analysis.company, analysis.title, analysis.location)
    rel_score = compute_initial_relevance(db, analysis, settings, manager)

    record = JobPostingRecord(
        session_id=session_row.id,
        url=canon_url or scraped.url,
        company=analysis.company,
        title=analysis.title,
        role_track=analysis.role_track,
        location=analysis.location,
        yoe_min=analysis.yoe.min_years,
        yoe_max=analysis.yoe.max_years,
        salary_min=analysis.salary.min_amount,
        salary_max=analysis.salary.max_amount,
        salary_currency=analysis.salary.currency,
        raw_text=scraped.raw_text,
        analysis_json=analysis.model_dump_json(),
        url_hash=u_hash,
        content_fingerprint=fp,
        source="manual",
        work_type=analysis.work_type,
        job_type=analysis.job_type,
        work_auth=analysis.work_auth,
        disposition="kept",
        application_status="ready",
        relevance_score=rel_score,
    )
    db.add(record)
    session_row.saved_count = int(session_row.saved_count or 0) + 1
    session_row.scanned_count = max(int(session_row.scanned_count or 0), session_row.saved_count)
    record_seen_job(
        db,
        url=canon_url or scraped.url,
        url_hash=u_hash,
        content_fingerprint=fp,
        company=analysis.company,
        title=analysis.title,
        location=analysis.location,
        source="manual",
        disposition="saved",
        session_id=session_row.id,
    )
    db.commit()
    db.refresh(record)
    return _job_to_response(record)


@router.post("/jobs/score", response_model=ATSReport)
def score_job(
    payload: ATSScoreRequest,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> ATSReport:
    """Score the matching role base resume (or chosen resume_id) against a scraped job posting."""
    job_row = db.get(JobPostingRecord, payload.job_id)
    if job_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found.")

    job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
    resume_row = _resolve_resume_record(
        db,
        payload.resume_id,
        preferred_role_track=job_analysis.role_track,
    )
    resume = CanonicalResume.model_validate_json(resume_row.content_json)

    return score_resume_against_job(
        job_id=job_row.id,
        resume_id=resume_row.id,
        resume=resume,
        job=job_analysis,
        rules=manager.get_rules(),
        settings=manager.get_settings(),
        raw_resume_text=resume_row.raw_text,
        raw_job_text=job_row.raw_text,
    )


@router.post("/tailor/preview", response_model=TailorPreviewResponse)
def preview_tailoring(
    payload: TailorPreviewRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> TailorPreviewResponse:
    """Generate a tailored, humanized, sanity-checked resume preview calibrated to 80-85%."""
    job_row = db.get(JobPostingRecord, payload.job_id)
    if job_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found.")

    job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
    resume_row = _resolve_resume_record(
        db,
        payload.resume_id,
        preferred_role_track=job_analysis.role_track,
    )
    base_resume = CanonicalResume.model_validate_json(resume_row.content_json)
    ollama_client = getattr(request.app.state, "ollama_http_client", None)

    return build_tailor_preview(
        job_id=job_row.id,
        resume_id=resume_row.id,
        resume_name=resume_row.name,
        base_resume=base_resume,
        job=job_analysis,
        rules=manager.get_rules(),
        settings=manager.get_settings(),
        raw_resume_text=resume_row.raw_text,
        job_raw_text=job_row.raw_text,
        adapt_location=payload.adapt_location,
        use_llm=payload.use_llm,
        tailor_strategy=payload.tailor_strategy,
        rehumanize=payload.rehumanize,
        bullets_per_experience=payload.bullets_per_experience,
        bullets_per_role_counts=payload.bullets_per_role_counts,
        bullets_per_project=payload.bullets_per_project,
        auto_size=payload.auto_size,
        page_budget=payload.page_budget,
        avoided_words=payload.avoided_words,
        custom_instructions=payload.custom_instructions,
        target_score=payload.target_score,
        target_score_min=payload.target_score_min,
        target_score_max=payload.target_score_max,
        llm_model=payload.llm_model,
        ollama_client=ollama_client,
        target_sections=payload.target_sections,
    )


@router.post("/tailor/score-draft", response_model=ATSReport)
def score_draft_resume(
    payload: DraftScoreRequest,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> ATSReport:
    """Compute live ATS match metrics for an in-progress edited CanonicalResume draft."""
    job_row = db.get(JobPostingRecord, payload.job_id)
    if job_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found.")

    job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
    resume_id = payload.resume_id or 0
    return score_resume_against_job(
        job_id=job_row.id,
        resume_id=resume_id,
        resume=payload.draft_resume,
        job=job_analysis,
        rules=manager.get_rules(),
        settings=manager.get_settings(),
        raw_resume_text=resume_to_plain_text(payload.draft_resume),
        raw_job_text=job_row.raw_text,
    )


@router.post("/tailor/section", response_model=TailorSectionResponse)
def tailor_resume_section(
    payload: TailorSectionRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> TailorSectionResponse:
    """Regenerate/tailor one resume section ('summary'|'experience'|'projects'|'skills') via prompt & engine."""
    job_row = db.get(JobPostingRecord, payload.job_id)
    if job_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found.")

    job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
    if job_row.raw_text:
        job_analysis = job_analysis.model_copy(
            update={"weighted_skills": enrich_job_weighted_skills(job_row.raw_text, job_analysis.weighted_skills)}
        )

    resume_row = _resolve_resume_record(
        db,
        payload.resume_id,
        preferred_role_track=job_analysis.role_track,
    )
    base_resume = CanonicalResume.model_validate_json(resume_row.content_json)
    settings = manager.get_settings()
    if payload.page_budget is not None:
        settings = settings.model_copy(update={"page_budget": float(payload.page_budget)})
    rules = manager.get_rules()
    ollama_client = getattr(request.app.state, "ollama_http_client", None)

    updated_resume, engine_used, model_used, report, added_skills, notice = tailor_resume_section_with_prompt(
        job=job_analysis,
        base_resume=base_resume,
        current_resume=payload.current_resume,
        section=payload.section,
        prompt=payload.prompt,
        engine=payload.engine,
        rules=rules,
        settings=settings,
        model=payload.model,
        avoided_words=payload.avoided_words,
        bullets_per_experience=payload.bullets_per_experience,
        client=ollama_client,
    )
    return TailorSectionResponse(
        job_id=job_row.id,
        resume_id=resume_row.id,
        section=payload.section,
        engine_used=engine_used,  # type: ignore[arg-type]
        model_used=model_used,
        updated_resume=updated_resume,
        tailored_score=report.overall_score,
        tailored_report=report.model_copy(update={"job_id": job_row.id, "resume_id": resume_row.id}),
        added_jd_skills=added_skills,
        notice=notice,
    )


@router.post("/tailor/humanize", response_model=HumanizeResumeResponse)
def humanize_draft_resume(
    payload: HumanizeResumeRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> HumanizeResumeResponse:
    """Scrub AI clichés, weak passive phrasing, and repeated verbs from a draft resume."""
    from backend.app.services.llm_tailor import humanize_resume, llm_tailor_and_humanize

    rules = manager.get_rules()
    settings = manager.get_settings()
    if payload.use_llm and payload.job_id is not None:
        job_row = db.get(JobPostingRecord, payload.job_id)
        if job_row is not None:
            job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
            ollama_client = getattr(request.app.state, "ollama_http_client", None)
            base_report = score_resume_against_job(
                job_id=job_row.id,
                resume_id=0,
                resume=payload.resume,
                job=job_analysis,
                rules=rules,
                settings=settings,
                raw_resume_text=resume_to_plain_text(payload.resume),
            )
            tailored, model_used, count, notes, err_note, _ = llm_tailor_and_humanize(
                base_resume=payload.resume,
                job=job_analysis,
                missing_skills=base_report.missing_skills,
                matched_skills=base_report.matched_skills,
                rules=rules,
                settings=settings,
                job_raw_text=job_row.raw_text,
                avoided_words=payload.avoided_words,
                client=ollama_client,
            )
            if err_note and err_note not in notes:
                notes = [err_note, *notes]
            return HumanizeResumeResponse(
                resume=tailored,
                changes_count=count,
                notes=notes,
                mode="ollama_llm" if model_used else "deterministic",
                model_used=model_used,
            )

    humanized, count, notes = humanize_resume(
        payload.resume,
        rules=rules,
        avoided_words=payload.avoided_words,
    )
    return HumanizeResumeResponse(
        resume=humanized,
        changes_count=count,
        notes=notes,
        mode="deterministic",
        model_used=None,
    )


@router.post("/export", response_model=ExportResponse, status_code=status.HTTP_201_CREATED)
def export_resume(
    payload: ExportRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> ExportResponse:
    """Generate .pdf / .docx files into output/<job_folder>/ and record run in SQLite."""
    job_row = db.get(JobPostingRecord, payload.job_id)
    if job_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job posting not found.")

    job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
    resume_row = _resolve_resume_record(
        db,
        payload.resume_id,
        preferred_role_track=job_analysis.role_track,
    )
    base_resume = CanonicalResume.model_validate_json(resume_row.content_json)
    effective_resume = payload.tailored_resume or base_resume
    settings = manager.get_settings()
    rules = manager.get_rules()

    base_report = score_resume_against_job(
        job_id=job_row.id,
        resume_id=resume_row.id,
        resume=base_resume,
        job=job_analysis,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_row.raw_text,
        raw_job_text=job_row.raw_text,
    )

    if payload.tailored_resume is not None:
        report = score_resume_against_job(
            job_id=job_row.id,
            resume_id=resume_row.id,
            resume=effective_resume,
            job=job_analysis,
            rules=rules,
            settings=settings,
            raw_resume_text=resume_to_plain_text(effective_resume),
            raw_job_text=job_row.raw_text,
        )
    else:
        report = base_report

    formats = payload.formats or list(settings.export_formats)
    output_root = _resolve_output_root(request, settings.output_dir)

    run = TailoringRunRecord(
        job_id=job_row.id,
        resume_id=resume_row.id,
        base_score=base_report.overall_score,
        tailored_score=report.overall_score,
        report_json=report.model_dump_json(),
        tailored_resume_json=json.dumps(effective_resume.model_dump(mode="json")),
        output_folder="",
    )
    db.add(run)
    db.flush()

    target_dir, generated_files, pdf_verified = export_run_artifacts(
        output_root=output_root,
        resume=effective_resume,
        job=job_analysis,
        report=report,
        formats=formats,
        filename_format=settings.resume_filename_format,
        page_budget=payload.page_budget or float(settings.page_budget),
        run_id=run.id,
    )
    run.output_folder = str(target_dir)
    if job_row.application_status in (None, "", "ready"):
        job_row.application_status = "resume_created"
    db.commit()
    db.refresh(run)

    return ExportResponse(
        run_id=run.id,
        job_id=job_row.id,
        resume_id=resume_row.id,
        ats_score=report.overall_score,
        output_folder=str(target_dir),
        folder_name=target_dir.name,
        generated_files=generated_files,
        pdf_text_verified=pdf_verified,
        report=report,
    )


@router.post("/sessions/{session_id}/bulk-export", response_model=BulkExportResponse)
def bulk_export_session_resumes(
    session_id: int,
    payload: BulkExportRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> BulkExportResponse:
    """Batch-tailor and export resumes for all saved (non-discarded) jobs in a session using seniority sizing."""
    session_row = db.get(ScrapeSessionRecord, session_id)
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    stmt = (
        select(JobPostingRecord)
        .where(
            JobPostingRecord.session_id == session_id,
            JobPostingRecord.disposition != "discarded",
        )
        .order_by(JobPostingRecord.relevance_score.desc(), JobPostingRecord.id.asc())
    )
    saved_jobs = list(db.scalars(stmt).all())
    candidates = [
        j
        for j in saved_jobs
        if payload.include_already_created or j.application_status != "resume_created"
    ]
    if payload.max_jobs is not None:
        candidates = candidates[: payload.max_jobs]

    settings = manager.get_settings()
    rules = manager.get_rules()
    formats = payload.formats or list(settings.export_formats) or ["pdf"]
    output_root = _resolve_output_root(request, settings.output_dir)
    ollama_client = getattr(request.app.state, "ollama_http_client", None)

    items: list[BulkExportJobItem] = []
    run_ids: list[int] = []
    succeeded = 0
    failed = 0

    for job_row in candidates:
        try:
            job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)
            resume_row = _resolve_resume_record(
                db,
                payload.resume_id,
                preferred_role_track=job_analysis.role_track,
            )
            base_resume = CanonicalResume.model_validate_json(resume_row.content_json)

            preview = build_tailor_preview(
                job_id=job_row.id,
                resume_id=resume_row.id,
                resume_name=resume_row.name,
                base_resume=base_resume,
                job=job_analysis,
                rules=rules,
                settings=settings,
                raw_resume_text=resume_row.raw_text,
                job_raw_text=job_row.raw_text,
                adapt_location=payload.adapt_location,
                tailor_strategy=payload.tailor_strategy,
                auto_size=payload.auto_size,
                avoided_words=payload.avoided_words,
                custom_instructions=payload.custom_instructions,
                target_score=payload.target_score_min,
                target_score_min=payload.target_score_min,
                target_score_max=payload.target_score_max,
                ollama_client=ollama_client,
            )

            run = TailoringRunRecord(
                job_id=job_row.id,
                resume_id=resume_row.id,
                base_score=preview.base_score,
                tailored_score=preview.tailored_score,
                report_json=preview.tailored_report.model_dump_json(),
                tailored_resume_json=json.dumps(preview.tailored_resume.model_dump(mode="json")),
                output_folder="",
            )
            db.add(run)
            db.flush()

            target_dir, generated_files, _ = export_run_artifacts(
                output_root=output_root,
                resume=preview.tailored_resume,
                job=job_analysis,
                report=preview.tailored_report,
                formats=formats,
                filename_format=settings.resume_filename_format,
                page_budget=preview.page_budget,
                run_id=run.id,
            )
            run.output_folder = str(target_dir)
            if job_row.application_status in (None, "", "ready"):
                job_row.application_status = "resume_created"

            doc_files = [f for f in generated_files if f.lower().endswith((".pdf", ".docx"))]
            run_ids.append(run.id)
            succeeded += 1
            items.append(
                BulkExportJobItem(
                    job_id=job_row.id,
                    run_id=run.id,
                    company=job_row.company,
                    title=job_row.title,
                    role_track=job_row.role_track,
                    yoe_snippet=job_analysis.yoe.raw_snippet,
                    base_score=preview.base_score,
                    tailored_score=preview.tailored_score,
                    in_target_band=preview.in_target_band,
                    page_budget=preview.page_budget,
                    bullets_per_role_counts=preview.bullets_per_role_counts,
                    tailor_mode=preview.tailor_mode,
                    sanity_passed=preview.sanity_passed,
                    generated_files=doc_files,
                    tailored_resume=preview.tailored_resume,
                    tailored_report=preview.tailored_report,
                )
            )
        except Exception as exc:
            failed += 1
            items.append(
                BulkExportJobItem(
                    job_id=job_row.id,
                    company=job_row.company,
                    title=job_row.title,
                    role_track=job_row.role_track,
                    error=str(exc),
                )
            )

    db.commit()
    ids_qs = ",".join(str(rid) for rid in run_ids)
    zip_url = f"/api/sessions/{session_id}/bulk-export/zip" + (f"?run_ids={ids_qs}" if ids_qs else "")
    return BulkExportResponse(
        session_id=session_id,
        total_saved_jobs=len(saved_jobs),
        processed_count=len(candidates),
        succeeded_count=succeeded,
        failed_count=failed,
        zip_download_url=zip_url,
        items=items,
    )


@router.get("/sessions/{session_id}/bulk-export/zip")
def download_bulk_export_zip(
    session_id: int,
    run_ids: str | None = None,
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    """Download a ZIP bundle containing generated PDF/DOCX resumes for a session."""
    session_row = db.get(ScrapeSessionRecord, session_id)
    if session_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scrape session not found.")

    selected_runs: list[TailoringRunRecord] = []
    if run_ids:
        parsed_ids = [int(tok.strip()) for tok in run_ids.split(",") if tok.strip().isdigit()]
        if parsed_ids:
            selected_runs = list(
                db.scalars(
                    select(TailoringRunRecord)
                    .where(TailoringRunRecord.id.in_(parsed_ids))
                    .order_by(TailoringRunRecord.id.asc())
                ).all()
            )
    else:
        job_ids = list(
            db.scalars(
                select(JobPostingRecord.id).where(
                    JobPostingRecord.session_id == session_id,
                    JobPostingRecord.disposition != "discarded",
                )
            ).all()
        )
        if job_ids:
            all_runs = list(
                db.scalars(
                    select(TailoringRunRecord)
                    .where(TailoringRunRecord.job_id.in_(job_ids))
                    .order_by(TailoringRunRecord.id.desc())
                ).all()
            )
            seen_j: set[int] = set()
            for r in all_runs:
                if r.job_id not in seen_j:
                    seen_j.add(r.job_id)
                    selected_runs.append(r)

    buf = io.BytesIO()
    files_added = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        used_arcnames: set[str] = set()
        for r in selected_runs:
            if not r.output_folder:
                continue
            folder = Path(r.output_folder)
            if not folder.is_dir():
                continue
            for file_path in sorted(folder.iterdir()):
                if file_path.is_file() and file_path.suffix.lower() in (".pdf", ".docx"):
                    arcname = file_path.name
                    if arcname in used_arcnames:
                        arcname = f"Run_{r.id}_{file_path.name}"
                    used_arcnames.add(arcname)
                    zf.write(file_path, arcname=arcname)
                    files_added += 1

    if files_added == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No generated resume files found for this session.")

    buf.seek(0)
    safe_sess = "".join(ch if ch.isalnum() else "_" for ch in (session_row.name or f"Session_{session_id}")).strip("_")[:48]
    zip_filename = f"CareerFlow_{safe_sess}_Resumes.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


@router.get("/export/runs")
def list_export_runs(db: Session = Depends(get_db_session)) -> list[dict[str, object]]:
    """List past generated resume output runs."""
    rows = db.scalars(select(TailoringRunRecord).order_by(TailoringRunRecord.id.desc())).all()
    items: list[dict[str, object]] = []
    for row in rows:
        folder = Path(row.output_folder) if row.output_folder else None
        files = [f.name for f in sorted(folder.iterdir())] if (folder and folder.exists()) else []
        items.append(
            {
                "run_id": row.id,
                "job_id": row.job_id,
                "resume_id": row.resume_id,
                "base_score": row.base_score,
                "tailored_score": row.tailored_score,
                "output_folder": row.output_folder,
                "folder_name": folder.name if folder else "",
                "files": files,
                "created_at": to_eastern(row.created_at),
            }
        )
    return items


@router.get("/skills-gap", response_model=SessionSkillsGapResponse)
def get_skills_gap_report(
    session_id: int | None = None,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> SessionSkillsGapResponse:
    """Aggregate weighted JD skill demand and base-resume coverage across active jobs."""
    return build_session_skills_gap(db=db, config_manager=manager, session_id=session_id)


@router.get("/reports", response_model=AnalyticsReportResponse)
def get_analytics_report(
    request: Request,
    session_id: int | None = None,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> AnalyticsReportResponse:
    """Return structured metrics for the Reports dashboard and write output/dashboard.html."""
    out_root = _resolve_output_root(request, manager.get_settings().output_dir)
    summary, _ = build_analytics_summary(
        db=db,
        config_manager=manager,
        session_id=session_id,
        write_html=True,
        output_dir=out_root,
    )
    return summary


@router.get("/reports/html", response_class=HTMLResponse)
def get_analytics_report_html(
    request: Request,
    session_id: int | None = None,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> HTMLResponse:
    """Return standalone dark-mode HTML metrics dashboard."""
    out_root = _resolve_output_root(request, manager.get_settings().output_dir)
    _, html = build_analytics_summary(
        db=db,
        config_manager=manager,
        session_id=session_id,
        write_html=True,
        output_dir=out_root,
    )
    return HTMLResponse(content=html)


@router.get("/reports/excel")
def download_analytics_excel(
    session_id: int | None = None,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> StreamingResponse:
    """Export multi-sheet Excel (.xlsx) workbook covering sessions, tracked jobs, applied standing, and skills."""
    xlsx_bytes = build_sessions_excel_workbook(
        db=db,
        config_manager=manager,
        session_id=session_id,
    )
    suffix = f"Session_{session_id}" if session_id is not None else "All_Sessions"
    filename = f"CareerFlow_Report_{suffix}.xlsx"
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/skills-graph", response_model=SkillsGraphResponse)
def get_skills_graph_report(
    session_id: int | None = None,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> SkillsGraphResponse:
    """Return structured Company x Role x Domain <-> Skills network graph from session job postings."""
    return build_skills_graph(db=db, config_manager=manager, session_id=session_id)


@router.post("/seen/clear-discarded")
def clear_seen_jobs(
    scope: str = "discarded",
    db: Session = Depends(get_db_session),
) -> dict[str, int]:
    """Allow user to reset discarded or auto-filtered seen ledger entries from Settings."""
    stmt = delete(SeenJobFingerprintRecord)
    if scope == "discarded":
        stmt = stmt.where(SeenJobFingerprintRecord.disposition == "discarded")
    elif scope == "auto_filtered":
        stmt = stmt.where(SeenJobFingerprintRecord.disposition == "auto_filtered")
    elif scope != "all":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scope must be 'discarded', 'auto_filtered', or 'all'.",
        )
    res = db.execute(stmt)
    db.commit()
    return {"cleared": int(res.rowcount or 0)}


@router.post("/data/flush", response_model=FlushDataResult)
def flush_workspace_data(
    payload: FlushDataRequest,
    request: Request,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> FlushDataResult:
    """Flush selected workspace data (or Master Flush keeping resumes & config)."""
    do_sessions = payload.master_flush or payload.flush_sessions_and_jobs
    do_resumes = payload.flush_resumes
    do_runs = payload.master_flush or payload.flush_tailoring_runs or do_sessions or do_resumes
    do_seen = payload.master_flush or payload.flush_seen_history
    seen_scope = "all" if payload.master_flush else payload.seen_scope
    do_output = payload.master_flush or payload.flush_output_files

    runs_deleted = 0
    jobs_deleted = 0
    sessions_deleted = 0
    seen_deleted = 0
    resumes_deleted = 0
    output_items_deleted = 0

    if do_runs or do_resumes or payload.master_flush:
        if do_runs:
            runs_deleted = int(db.execute(delete(TailoringRunRecord)).rowcount or 0)
        if not do_sessions:
            db.execute(
                update(JobPostingRecord)
                .where(JobPostingRecord.application_status == "resume_created")
                .values(application_status="ready")
            )

    if do_sessions:
        db.execute(delete(SessionFilteredJobRecord))
        jobs_deleted = int(db.execute(delete(JobPostingRecord)).rowcount or 0)
        sessions_deleted = int(db.execute(delete(ScrapeSessionRecord)).rowcount or 0)
        request.app.state.scrape_progress = ScrapeProgressStore()

    if do_seen:
        seen_stmt = delete(SeenJobFingerprintRecord)
        if seen_scope == "discarded":
            seen_stmt = seen_stmt.where(SeenJobFingerprintRecord.disposition == "discarded")
        elif seen_scope == "auto_filtered":
            seen_stmt = seen_stmt.where(SeenJobFingerprintRecord.disposition == "auto_filtered")
        seen_deleted = int(db.execute(seen_stmt).rowcount or 0)

    if do_resumes:
        resumes_deleted = int(db.execute(delete(ResumeRecord)).rowcount or 0)

    db.commit()

    if do_output:
        out_root = _resolve_output_root(request, manager.get_settings().output_dir)
        if out_root.exists() and out_root.is_dir():
            for child in list(out_root.iterdir()):
                try:
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
                    output_items_deleted += 1
                except OSError:
                    pass

    return FlushDataResult(
        sessions_deleted=sessions_deleted,
        jobs_deleted=jobs_deleted,
        tailoring_runs_deleted=runs_deleted,
        seen_deleted=seen_deleted,
        resumes_deleted=resumes_deleted,
        output_items_deleted=output_items_deleted,
    )


@router.get("/export/runs/{run_id}/download/{filename}")
def download_export_artifact(
    run_id: int,
    filename: str,
    db: Session = Depends(get_db_session),
) -> FileResponse:
    """Download a generated resume artifact (.pdf, .docx, or JSON snapshot)."""
    clean_name = Path(filename).name
    if clean_name != filename or Path(clean_name).suffix.lower() not in ALLOWED_DOWNLOAD_SUFFIXES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported download filename.")

    run = db.get(TailoringRunRecord, run_id)
    if run is None or not run.output_folder:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Export run not found.")

    folder_root = Path(run.output_folder).resolve()
    file_path = (folder_root / clean_name).resolve()
    if file_path.parent != folder_root or not file_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Requested artifact file not found.")

    return FileResponse(path=str(file_path), filename=clean_name)
