"""Endpoints for managing base resumes, web builder saves, and uploaded context files."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_config_manager, get_db_session
from backend.app.db.models import ResumeRecord
from backend.app.schemas.resume import (
    CanonicalResume,
    ResumeBootstrapRequest,
    ResumeBootstrapResponse,
    ResumeCreateRequest,
    ResumeRecordResponse,
)
from backend.app.services.config_manager import ConfigManager
from backend.app.services.resume_parser import parse_uploaded_resume, resume_to_plain_text
from backend.app.services.timezone_utils import now_eastern, to_eastern

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


def _to_response(record: ResumeRecord) -> ResumeRecordResponse:
    return ResumeRecordResponse(
        id=record.id,
        name=record.name,
        role_track=record.role_track or "senior_swe",
        is_base=record.is_base,
        source_type=record.source_type,
        source_filename=record.source_filename,
        content=CanonicalResume.model_validate_json(record.content_json),
        raw_text=record.raw_text,
        created_at=to_eastern(record.created_at) or now_eastern(),
        updated_at=to_eastern(record.updated_at) or now_eastern(),
    )


def _clear_existing_base_flags(db: Session, role_track: str) -> None:
    existing_bases = db.scalars(
        select(ResumeRecord).where(
            ResumeRecord.is_base.is_(True),
            ResumeRecord.role_track == role_track,
        )
    ).all()
    for row in existing_bases:
        row.is_base = False


@router.get("")
def list_resumes(db: Session = Depends(get_db_session)) -> dict[str, object]:
    """List saved resumes and report active base resumes across role profiles."""
    rows = db.scalars(select(ResumeRecord).order_by(ResumeRecord.is_base.desc(), ResumeRecord.id.desc())).all()
    items = [_to_response(r) for r in rows]
    base_resume = next((r for r in items if r.is_base), None)
    base_by_role: dict[str, int] = {}
    for item in items:
        if item.is_base and item.role_track not in base_by_role:
            base_by_role[item.role_track] = item.id
    return {
        "has_base_resume": base_resume is not None,
        "base_resume_id": base_resume.id if base_resume else None,
        "base_by_role": base_by_role,
        "resumes": items,
    }


@router.post("", response_model=ResumeRecordResponse, status_code=status.HTTP_201_CREATED)
def create_resume(
    payload: ResumeCreateRequest,
    db: Session = Depends(get_db_session),
) -> ResumeRecordResponse:
    """Create a resume from the Web UI form."""
    role_track = (payload.role_track or "senior_swe").strip() or "senior_swe"
    if payload.is_base:
        _clear_existing_base_flags(db, role_track)

    record = ResumeRecord(
        name=payload.name,
        role_track=role_track,
        is_base=payload.is_base,
        source_type="form",
        source_filename=None,
        content_json=payload.content.model_dump_json(),
        raw_text=resume_to_plain_text(payload.content),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _to_response(record)


@router.post("/upload", response_model=ResumeRecordResponse, status_code=status.HTTP_201_CREATED)
async def upload_resume(
    file: UploadFile = File(...),
    name: str = Form("Uploaded Base Resume"),
    role_track: str = Form("senior_swe"),
    is_base: bool = Form(True),
    db: Session = Depends(get_db_session),
) -> ResumeRecordResponse:
    """Upload a .pdf, .docx, .tex, or .txt resume and parse into CanonicalResume."""
    filename = file.filename or "resume.txt"
    content_bytes = await file.read()
    if not content_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    try:
        source_type, canonical, raw_text = parse_uploaded_resume(filename, content_bytes)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Could not parse '{filename}': {exc}",
        ) from exc

    track = (role_track or "senior_swe").strip() or "senior_swe"
    if is_base:
        _clear_existing_base_flags(db, track)

    record = ResumeRecord(
        name=name,
        role_track=track,
        is_base=is_base,
        source_type=source_type,
        source_filename=filename,
        content_json=canonical.model_dump_json(),
        raw_text=raw_text or resume_to_plain_text(canonical),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return _to_response(record)


@router.post("/bootstrap", response_model=ResumeBootstrapResponse, status_code=status.HTTP_201_CREATED)
def bootstrap_generic_resume(
    payload: ResumeBootstrapRequest,
    request: Request,
    db: Session = Depends(get_db_session),
    manager: ConfigManager = Depends(get_config_manager),
) -> ResumeBootstrapResponse:
    """Auto-generate a recruiter-grade quantified generic resume when no base resume exists."""
    from backend.app.db.models import JobPostingRecord
    from backend.app.schemas.job import JobAnalysis
    from backend.app.services.llm_tailor import generate_generic_base_resume

    role_track = (payload.role_track or "senior_swe").strip() or "senior_swe"
    try:
        track = manager.get_role_track(role_track)
    except ValueError:
        tracks = manager.list_role_tracks()
        if not tracks:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No role tracks configured.")
        track = tracks[0]
        role_track = track.id

    job_analysis = None
    if payload.job_id is not None:
        job_row = db.get(JobPostingRecord, payload.job_id)
        if job_row is not None:
            job_analysis = JobAnalysis.model_validate_json(job_row.analysis_json)

    ollama_client = getattr(request.app.state, "ollama_http_client", None)
    canonical, gen_mode, model_used, humanized_count, notes = generate_generic_base_resume(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        location=payload.location,
        track=track,
        years_experience=payload.years_experience,
        focus_skills=payload.focus_skills,
        rules=manager.get_rules(),
        settings=manager.get_settings(),
        job=job_analysis,
        use_llm=payload.use_llm,
        client=ollama_client,
        employers=payload.employers,
        recent_company=payload.recent_company,
        prior_company=payload.prior_company,
        graduate_degree=payload.graduate_degree,
        undergrad_degree=payload.undergrad_degree,
        bullets_per_experience=payload.bullets_per_experience,
        bullets_per_role_counts=payload.bullets_per_role_counts,
        projects_count=payload.projects_count,
        page_budget=payload.page_budget,
    )

    if payload.save_as_base:
        _clear_existing_base_flags(db, role_track)

    resume_name = (
        (payload.resume_name or "").strip()
        or f"{canonical.contact.full_name} — {track.display_name} ({payload.years_experience}y Base)"
    )
    record = ResumeRecord(
        name=resume_name,
        role_track=role_track,
        is_base=payload.save_as_base,
        source_type="generated_template",
        source_filename=None,
        content_json=canonical.model_dump_json(),
        raw_text=resume_to_plain_text(canonical),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return ResumeBootstrapResponse(
        resume=_to_response(record),
        generation_mode=gen_mode,  # type: ignore[arg-type]
        model_used=model_used,
        humanized_count=humanized_count,
        notes=notes,
    )


@router.put("/{resume_id}", response_model=ResumeRecordResponse)
def update_resume(
    resume_id: int,
    payload: ResumeCreateRequest,
    db: Session = Depends(get_db_session),
) -> ResumeRecordResponse:
    """Update a stored resume's canonical content or promote it as active base resume."""
    record = db.get(ResumeRecord, resume_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found.")

    role_track = (payload.role_track or record.role_track or "senior_swe").strip() or "senior_swe"
    if payload.is_base:
        _clear_existing_base_flags(db, role_track)

    record.name = payload.name
    record.role_track = role_track
    record.is_base = payload.is_base
    record.content_json = json.dumps(payload.content.model_dump(mode="json"))
    record.raw_text = resume_to_plain_text(payload.content)
    db.commit()
    db.refresh(record)
    return _to_response(record)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: int, db: Session = Depends(get_db_session)) -> None:
    """Delete a stored resume record."""
    record = db.get(ResumeRecord, resume_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found.")
    db.delete(record)
    db.commit()
