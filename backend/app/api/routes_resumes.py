"""Endpoints for managing base resumes, web builder saves, and uploaded context files."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db_session
from backend.app.db.models import ResumeRecord
from backend.app.schemas.resume import (
    CanonicalResume,
    ResumeCreateRequest,
    ResumeRecordResponse,
)
from backend.app.services.resume_parser import parse_uploaded_resume, resume_to_plain_text

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
        created_at=record.created_at,
        updated_at=record.updated_at,
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
