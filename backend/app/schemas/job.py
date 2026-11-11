"""Job ingestion, sessions, weighted skills, ATS scoring, comparison preview, and export schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from backend.app.schemas.resume import CanonicalResume

SkillTier = Literal[
    "core_must_have",
    "important_systems",
    "senior_leadership",
    "bonus_nice_to_have",
]


class ScrapeSessionCreateRequest(BaseModel):
    """Create a named job-scraping session."""

    name: str
    posted_within: Optional[str] = None


class ScrapeSessionLocationCount(BaseModel):
    """Aggregated posting count per location inside a scrape session."""

    location: str
    count: int


class ScrapeSessionRoleCount(BaseModel):
    """Aggregated posting count per target role inside a scrape session."""

    role_track: str
    count: int


class ScrapeSessionSummary(BaseModel):
    """Session overview with grouped location, role, and salary-currency metrics."""

    id: int
    name: str
    total_jobs: int
    posted_within: str = "24h"
    scanned_count: int = 0
    saved_count: int = 0
    filtered_count: int = 0
    filter_breakdown: dict[str, int] = Field(default_factory=dict)
    source_notes: list[str] = Field(default_factory=list)
    locations: list[ScrapeSessionLocationCount] = Field(default_factory=list)
    roles: list[ScrapeSessionRoleCount] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    created_at: datetime


class JobIngestRequest(BaseModel):
    """Request to scrape a job posting URL and/or analyze pasted JD text."""

    session_id: Optional[int] = None
    url: Optional[str] = None
    raw_text: Optional[str] = None
    company_override: Optional[str] = None
    title_override: Optional[str] = None
    location_override: Optional[str] = None
    role_track: Optional[str] = None

    @model_validator(mode="after")
    def require_url_or_text(self) -> "JobIngestRequest":
        has_url = bool(self.url and self.url.strip())
        has_text = bool(self.raw_text and self.raw_text.strip())
        if not has_url and not has_text:
            raise ValueError("Provide either a job posting url or raw_text.")
        return self


class WeightedSkill(BaseModel):
    """Extracted skill or technical signal with JD priority weight."""

    keyword: str
    tier: SkillTier
    priority_label: str
    weight: float
    jd_mentions: int = 1
    in_required_section: bool = False


class SalaryInfo(BaseModel):
    """Parsed compensation bounds and comparison against target USD salary floor."""

    min_amount: Optional[int] = None
    max_amount: Optional[int] = None
    currency: str = "USD"
    period: str = "year"
    raw_snippet: Optional[str] = None
    meets_target: Optional[bool] = None


class YoeInfo(BaseModel):
    """Parsed years-of-experience requirement and fit with 4-8 YoE target."""

    min_years: Optional[int] = None
    max_years: Optional[int] = None
    raw_snippet: Optional[str] = None
    fits_target_range: Optional[bool] = None


class JobAnalysis(BaseModel):
    """Structured analysis of a scraped or pasted job description."""

    company: str = "Unknown Company"
    title: str = "Untitled Role"
    location: str = ""
    role_track: str = "senior_swe"
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    yoe: YoeInfo = Field(default_factory=YoeInfo)
    weighted_skills: list[WeightedSkill] = Field(default_factory=list)
    expected_work: list[str] = Field(default_factory=list)
    detected_signals: list[str] = Field(default_factory=list)
    work_type: str = "unspecified"
    job_type: str = "full-time"
    work_auth: str = "unspecified"


class JobPostingResponse(BaseModel):
    """Stored job posting and weighted analysis."""

    id: int
    session_id: Optional[int] = None
    url: Optional[str] = None
    analysis: JobAnalysis
    raw_text: str
    source: str = "manual"
    posted_at: Optional[datetime] = None
    work_type: str = "unspecified"
    job_type: str = "full-time"
    work_auth: str = "unspecified"
    disposition: str = "kept"
    application_status: str = "ready"
    relevance_score: float = 0.0
    created_at: datetime


class BulletDiagnostic(BaseModel):
    """Per-bullet quality, XYZ impact, and humanizer diagnostic."""

    section: str
    parent_name: str
    bullet_text: str
    has_strong_verb: bool
    has_quantified_metric: bool
    weak_phrases_found: list[str] = Field(default_factory=list)
    ai_slop_found: list[str] = Field(default_factory=list)
    exceeds_max_length: bool = False


class ATSScoreRequest(BaseModel):
    """Request to score a stored resume against a stored job posting."""

    job_id: int
    resume_id: Optional[int] = None


class ATSReport(BaseModel):
    """Deterministic Big Tech ATS match scorecard and ranked gap list."""

    job_id: int
    resume_id: int
    overall_score: float
    sub_scores: dict[str, float]
    matched_skills: list[WeightedSkill] = Field(default_factory=list)
    missing_skills: list[WeightedSkill] = Field(default_factory=list)
    bullet_diagnostics: list[BulletDiagnostic] = Field(default_factory=list)
    format_warnings: list[str] = Field(default_factory=list)
    estimated_pages: int = 1


class FieldChange(BaseModel):
    """Visible non-bullet field adjustment such as tailoring candidate city to job location."""

    field_name: str
    before: str
    after: str
    reason: str


class BulletComparison(BaseModel):
    """Before vs. Tailored comparison for a single experience bullet."""

    bullet_id: str
    original_text: str
    tailored_text: str
    status: Literal["unchanged", "polished", "reordered", "edited"]
    matched_keywords: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ExperienceComparison(BaseModel):
    """Side-by-side comparison across each work experience role."""

    experience_id: str
    company: str
    title: str
    dates: str
    bullets: list[BulletComparison] = Field(default_factory=list)


class TailorPreviewRequest(BaseModel):
    """Request a pre-export side-by-side comparison & fact-check preview."""

    job_id: int
    resume_id: Optional[int] = None
    adapt_location: bool = True


class TailorPreviewResponse(BaseModel):
    """Pre-export comparison showing location changes, per-experience diffs, and score delta."""

    job_id: int
    resume_id: int
    resume_name: str
    base_score: float
    tailored_score: float
    base_report: ATSReport
    tailored_report: ATSReport
    field_changes: list[FieldChange] = Field(default_factory=list)
    experience_comparisons: list[ExperienceComparison] = Field(default_factory=list)
    tailored_resume: CanonicalResume


class ExportRequest(BaseModel):
    """Request to export a resume for a job posting into output/<folder>/."""

    job_id: int
    resume_id: Optional[int] = None
    formats: Optional[list[Literal["pdf", "docx"]]] = None
    tailored_resume: Optional[CanonicalResume] = None


class ExportResponse(BaseModel):
    """Generated output folder metadata and downloadable artifact filenames."""

    run_id: int
    job_id: int
    resume_id: int
    ats_score: float
    output_folder: str
    folder_name: str
    generated_files: list[str]
    pdf_text_verified: Optional[bool] = None
    report: ATSReport


class ScrapeBatchRequest(BaseModel):
    """Trigger automated job discovery and simultaneous inline filtering for a session."""

    posted_within: Optional[str] = None
    role_tracks: Optional[list[str]] = None
    locations: Optional[list[str]] = None
    sources: Optional[list[str]] = None
    company_boards: Optional[list[str]] = None
    max_per_source: int = Field(default=40, ge=1, le=200)


class FilteredJobSample(BaseModel):
    """Sample summary of a posting dropped during simultaneous inline scraping."""

    title: str
    company: str
    location: str
    source: str
    reason: str
    url: Optional[str] = None


class ScrapeBatchResult(BaseModel):
    """Outcome summary of an automated batch scrape run."""

    session_id: int
    posted_within: str
    scanned_count: int
    saved_count: int
    filtered_count: int
    duplicate_skipped_count: int
    filter_breakdown: dict[str, int] = Field(default_factory=dict)
    source_notes: list[str] = Field(default_factory=list)
    saved_jobs: list[JobPostingResponse] = Field(default_factory=list)
    filtered_samples: list[FilteredJobSample] = Field(default_factory=list)


class JobPatchRequest(BaseModel):
    """Update Keep/Discard disposition or application workflow status on a job posting."""

    disposition: Optional[Literal["kept", "discarded"]] = None
    application_status: Optional[Literal["ready", "resume_created", "applied", "skipped"]] = None


class SessionSkillGapItem(BaseModel):
    """Aggregated skill frequency and resume coverage across active session jobs."""

    keyword: str
    tier: str
    priority_label: str
    demand_count: int
    demand_pct: float
    covered_by_resumes: list[str] = Field(default_factory=list)
    is_covered: bool


class RoleGapBreakdown(BaseModel):
    """Skills-gap slice grouped by target role track."""

    role_track: str
    job_count: int
    has_base_resume: bool
    avg_relevance: float
    top_missing_skills: list[SessionSkillGapItem] = Field(default_factory=list)
    top_matched_skills: list[SessionSkillGapItem] = Field(default_factory=list)


class SessionSkillsGapResponse(BaseModel):
    """Cross-posting skills gap summary for a session or the whole workspace."""

    session_id: Optional[int] = None
    session_name: str
    total_active_jobs: int
    covered_skill_count: int
    missing_skill_count: int
    overall_missing: list[SessionSkillGapItem] = Field(default_factory=list)
    overall_strengths: list[SessionSkillGapItem] = Field(default_factory=list)
    by_role: list[RoleGapBreakdown] = Field(default_factory=list)


class ReportBucketItem(BaseModel):
    """Labeled bucket metric for analytics visualizations."""

    label: str
    count: int
    pct: float


class AnalyticsReportResponse(BaseModel):
    """Workspace or session analytics metrics backing the interactive UI & HTML report."""

    generated_at: datetime
    session_id: Optional[int] = None
    session_name: str
    total_sessions: int
    total_scanned: int
    total_saved: int
    total_filtered: int
    total_discarded: int
    seen_ledger_count: int
    omitted_salary_count: int
    avg_relevance_score: float
    total_exports: int
    by_location: list[ReportBucketItem] = Field(default_factory=list)
    by_role: list[ReportBucketItem] = Field(default_factory=list)
    by_source: list[ReportBucketItem] = Field(default_factory=list)
    by_currency: list[ReportBucketItem] = Field(default_factory=list)
    by_status: list[ReportBucketItem] = Field(default_factory=list)
    by_filter_reason: list[ReportBucketItem] = Field(default_factory=list)
    top_missing_skills: list[SessionSkillGapItem] = Field(default_factory=list)
    html_report_path: Optional[str] = None
