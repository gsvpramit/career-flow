"""Canonical resume and ATS evaluation schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

BulletProvenance = Literal[
    "VERIFIED_BASE",
    "BANK_PULLED",
    "REFRAMED",
    "SUGGESTED_DRAFT",
]


class ContactInfo(BaseModel):
    """Candidate contact header (omits physical home address per Big Tech standard)."""

    full_name: str
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""


class EducationItem(BaseModel):
    """Academic degree entry."""

    institution: str
    degree: str
    location: str = ""
    graduation_date: str = ""
    gpa: Optional[str] = None
    coursework: list[str] = Field(default_factory=list)


class ExperienceBullet(BaseModel):
    """Single achievement bullet with provenance tracking for human-in-the-loop tailoring."""

    id: str = ""
    text: str
    provenance: BulletProvenance = "VERIFIED_BASE"
    approved: bool = True
    tags: list[str] = Field(default_factory=list)


class ExperienceItem(BaseModel):
    """Employment role entry with locked identity anchors."""

    id: str = ""
    company: str
    title: str
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    bullets: list[ExperienceBullet] = Field(default_factory=list)


class ProjectItem(BaseModel):
    """Technical project entry."""

    id: str = ""
    name: str
    tech_stack: list[str] = Field(default_factory=list)
    link: str = ""
    bullets: list[ExperienceBullet] = Field(default_factory=list)


class SkillCategory(BaseModel):
    """Categorized technical skills row (e.g., Languages, Frameworks, Cloud/DevOps)."""

    category: str
    items: list[str] = Field(default_factory=list)


class CertificationItem(BaseModel):
    """Professional certification or credential entry."""

    name: str
    issuer: str = ""
    date: str = ""
    credential_url: str = ""


class CanonicalResume(BaseModel):
    """Single Source of Truth resume structure rendered to PDF, DOCX, and future TEX."""

    contact: ContactInfo
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certifications: list[CertificationItem] = Field(default_factory=list)
    skills: list[SkillCategory] = Field(default_factory=list)
    summary: Optional[str] = None


class ResumeCreateRequest(BaseModel):
    """Payload to create or update a resume from the Web UI form."""

    name: str = "Primary Base Resume"
    role_track: str = "senior_swe"
    is_base: bool = True
    content: CanonicalResume


class ResumeRecordResponse(BaseModel):
    """Stored resume record returned by the API."""

    id: int
    name: str
    role_track: str
    is_base: bool
    source_type: str
    source_filename: Optional[str] = None
    content: CanonicalResume
    raw_text: str = ""
    created_at: datetime
    updated_at: datetime
