"""Endpoints for job scraping, weighted analysis, ATS scoring, and multi-format export."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_config_manager, get_db_session
from backend.app.config import PROJECT_ROOT
from backend.app.db.models import (
    JobPostingRecord,
    ResumeRecord,
    ScrapeSessionRecord,
    SeenJobFingerprintRecord,
    TailoringRunRecord,
)
from backend.app.schemas.job import (
    AnalyticsReportResponse,
    ATSReport,
    ATSScoreRequest,
    ExportRequest,
    ExportResponse,
    JobAnalysis,
    JobIngestRequest,
    JobPatchRequest,
    JobPostingResponse,
    ScrapeBatchRequest,
    ScrapeBatchResult,
    ScrapeSessionCreateRequest,
    ScrapeSessionLocationCount,
    ScrapeSessionRoleCount,
    ScrapeSessionSummary,
    SessionSkillsGapResponse,
    TailorPreviewRequest,
    TailorPreviewResponse,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.batch_scraper import (
    canonicalize_url,
    compute_initial_relevance,
    hash_url,
    make_content_fingerprint,
    record_seen_job,
    run_batch_scrape,
)
from backend.app.services.config_manager import ConfigManager
from backend.app.services.exporter import export_run_artifacts
from backend.app.services.jd_analyzer import analyze_job_posting, infer_header_metadata
from backend.app.services.reports import build_analytics_summary, build_session_skills_gap
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.scraper import ScrapeError, fetch_job_posting
from backend.app.services.tailor import build_tailor_preview

router = APIRouter(prefix="/api", tags=["jobs-and-export"])

ALLOWED_DOWNLOAD_SUFFIXES = {".pdf", ".docx", ".json", ".html"}


def _job_to_response(row: JobPostingRecord) -> JobPostingResponse:
    return JobPostingResponse(
        id=row.id,
        session_id=row.session_id,
        url=row.url,
        analysis=JobAnalysis.model_validate_json(row.analysis_json),
        raw_text=row.raw_text,
        source=row.source or "manual",
        posted_at=row.posted_at,
        work_type=row.work_type or "unspecified",
        job_type=row.job_type or "full-time",
        work_auth=row.work_auth or "unspecified",
        disposition=row.disposition or "kept",
        application_status=row.application_status or "ready",
        relevance_score=float(row.relevance_score or 0.0),
        created_at=row.created_at,
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
    candidate = Path(settings_output_dir)
    return candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)


def _build_session_summary(db: Session, session_row: ScrapeSessionRecord) -> ScrapeSessionSummary:
    jobs = db.scalars(
        select(JobPostingRecord)
        .where(
            JobPostingRecord.session_id == session_row.id,
            JobPostingRecord.disposition != "discarded",
        )
        .order_by(JobPostingRecord.id.desc())
    ).all()

    location_counts: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    currencies: list[str] = []

    for job in jobs:
        loc_label = (job.location or "").strip() or "Unspecified"
        location_counts[loc_label] += 1
        role_counts[job.role_track or "senior_swe"] += 1
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

    return ScrapeSessionSummary(
        id=session_row.id,
        name=session_row.name,
        total_jobs=len(jobs),
        posted_within=session_row.posted_within or "24h",
        scanned_count=int(session_row.scanned_count or 0),
        saved_count=int(session_row.saved_count or 0),
        filtered_count=int(session_row.filtered_count or 0),
        filter_breakdown=json.loads(session_row.filter_breakdown_json or "{}"),
        source_notes=json.loads(session_row.source_notes_json or "[]"),
        locations=locations,
        roles=roles,
        currencies=currencies,
        created_at=session_row.created_at,
    )


def _default_session_name(db: Session) -> str:
    existing_count = len(db.scalars(select(ScrapeSessionRecord.id)).all())
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
    )


@router.post("/tailor/preview", response_model=TailorPreviewResponse)
def preview_tailoring(
    payload: TailorPreviewRequest,
    manager: ConfigManager = Depends(get_config_manager),
    db: Session = Depends(get_db_session),
) -> TailorPreviewResponse:
    """Generate a pre-export side-by-side comparison, location adaptation, and ATS delta."""
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

    return build_tailor_preview(
        job_id=job_row.id,
        resume_id=resume_row.id,
        resume_name=resume_row.name,
        base_resume=base_resume,
        job=job_analysis,
        rules=manager.get_rules(),
        settings=manager.get_settings(),
        raw_resume_text=resume_row.raw_text,
        adapt_location=payload.adapt_location,
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
        )
    else:
        report = base_report

    formats = payload.formats or list(settings.export_formats)
    output_root = _resolve_output_root(request, settings.output_dir)
    target_dir, generated_files, pdf_verified = export_run_artifacts(
        output_root=output_root,
        resume=effective_resume,
        job=job_analysis,
        report=report,
        formats=formats,
        filename_format=settings.resume_filename_format,
    )

    run = TailoringRunRecord(
        job_id=job_row.id,
        resume_id=resume_row.id,
        base_score=base_report.overall_score,
        tailored_score=report.overall_score,
        report_json=report.model_dump_json(),
        tailored_resume_json=json.dumps(effective_resume.model_dump(mode="json")),
        output_folder=str(target_dir),
    )
    if job_row.application_status in (None, "", "ready"):
        job_row.application_status = "resume_created"
    db.add(run)
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
                "created_at": row.created_at,
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
