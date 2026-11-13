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

ApplicationStatusLiteral = Literal[
    "ready",
    "resume_created",
    "applied",
    "screening",
    "interviewing",
    "offer",
    "rejected",
    "skipped",
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
    """Session overview with grouped location, role, status, and source metrics."""

    id: int
    name: str
    total_jobs: int
    posted_within: str = "24h"
    scanned_count: int = 0
    saved_count: int = 0
    filtered_count: int = 0
    seen_skipped_count: int = 0
    discarded_count: int = 0
    filter_breakdown: dict[str, int] = Field(default_factory=dict)
    source_notes: list[str] = Field(default_factory=list)
    locations: list[ScrapeSessionLocationCount] = Field(default_factory=list)
    roles: list[ScrapeSessionRoleCount] = Field(default_factory=list)
    currencies: list[str] = Field(default_factory=list)
    status_counts: dict[str, int] = Field(default_factory=dict)
    sources_used: list[str] = Field(default_factory=list)
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
    applied_at: Optional[datetime] = None
    application_notes: str = ""
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
    resume_skills: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    bullet_diagnostics: list[BulletDiagnostic] = Field(default_factory=list)
    format_warnings: list[str] = Field(default_factory=list)
    estimated_pages: int = 1


class SanityCheckItem(BaseModel):
    """Single real-world plausibility & guardrail check executed after tailoring."""

    check_id: str
    title: str
    status: Literal["passed", "repaired", "warning"]
    detail: str


class TailoringReasoningStep(BaseModel):
    """Transparent step from the tailoring engine explaining what changed and why."""

    step: int
    phase: str
    decision: str


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
    """Request a pre-export side-by-side comparison, humanization, sanity check, and score preview."""

    job_id: int
    resume_id: Optional[int] = None
    adapt_location: bool = True
    use_llm: Optional[bool] = None
    tailor_strategy: Literal["ollama", "claude", "auto", "fallback_script"] = "ollama"
    target_sections: Optional[list[Literal["summary", "experience", "projects", "skills"]]] = None
    rehumanize: bool = False
    bullets_per_experience: Optional[int] = Field(default=None, ge=2, le=12)
    bullets_per_role_counts: Optional[list[int]] = None
    bullets_per_project: Optional[int] = Field(default=None, ge=1, le=8)
    auto_size: bool = False
    page_budget: Optional[float] = Field(default=None, ge=1.0, le=4.0)
    avoided_words: Optional[list[str]] = None
    custom_instructions: Optional[str] = None
    target_score: int = Field(default=80, ge=50, le=100)
    target_score_min: int = Field(default=80, ge=50, le=95)
    target_score_max: int = Field(default=85, ge=55, le=100)
    llm_model: Optional[str] = None


class TailorPreviewResponse(BaseModel):
    """Pre-export comparison showing location changes, per-experience diffs, reasoning, sanity checks, and score band."""

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
    tailor_mode: Literal["deterministic", "fallback_script", "ollama_llm", "claude"] = "fallback_script"
    model_used: Optional[str] = None
    humanized_count: int = 0
    humanizer_notes: list[str] = Field(default_factory=list)
    llm_notice: Optional[str] = None
    added_jd_skills: list[str] = Field(default_factory=list)
    target_score_met: bool = False
    target_score_min: int = 80
    target_score_max: int = 85
    in_target_band: bool = False
    bullets_per_experience: Optional[int] = None
    bullets_per_role_counts: list[int] = Field(default_factory=list)
    bullets_per_project: Optional[int] = None
    page_budget: float = 1.5
    reasoning_steps: list[TailoringReasoningStep] = Field(default_factory=list)
    sanity_checks: list[SanityCheckItem] = Field(default_factory=list)
    sanity_passed: bool = True
    sanity_summary: str = ""


class ExportRequest(BaseModel):
    """Request to export a resume for a job posting."""

    job_id: int
    resume_id: Optional[int] = None
    formats: Optional[list[Literal["pdf", "docx"]]] = None
    tailored_resume: Optional[CanonicalResume] = None
    page_budget: Optional[float] = Field(default=None, ge=1.0, le=4.0)


class ExportResponse(BaseModel):
    """Generated export run metadata and downloadable artifact filenames."""

    run_id: int
    job_id: int
    resume_id: int
    ats_score: float
    output_folder: str
    folder_name: str
    generated_files: list[str]
    pdf_text_verified: Optional[bool] = None
    report: ATSReport


class BulkExportRequest(BaseModel):
    """Batch-generate tailored resumes for all kept/saved jobs in a scrape session."""

    resume_id: Optional[int] = None
    formats: list[Literal["pdf", "docx"]] = Field(default_factory=lambda: ["pdf"])
    tailor_strategy: Literal["ollama", "claude", "auto", "fallback_script"] = "ollama"
    target_sections: Optional[list[Literal["summary", "experience", "projects", "skills"]]] = None
    adapt_location: bool = True
    auto_size: bool = True
    target_score_min: int = Field(default=80, ge=50, le=95)
    target_score_max: int = Field(default=85, ge=55, le=100)
    include_already_created: bool = True
    max_jobs: Optional[int] = Field(default=None, ge=1, le=200)
    avoided_words: Optional[list[str]] = None
    custom_instructions: Optional[str] = None


class BulkExportJobItem(BaseModel):
    """Outcome record for a single job processed in a session batch export."""

    job_id: int
    run_id: int = 0
    company: str
    title: str
    role_track: str
    yoe_snippet: Optional[str] = None
    base_score: float = 0.0
    tailored_score: float = 0.0
    in_target_band: bool = False
    page_budget: float = 1.5
    bullets_per_role_counts: list[int] = Field(default_factory=list)
    tailor_mode: str = "fallback_script"
    sanity_passed: bool = True
    generated_files: list[str] = Field(default_factory=list)
    tailored_resume: Optional[CanonicalResume] = None
    tailored_report: Optional[ATSReport] = None
    error: Optional[str] = None


class BulkExportResponse(BaseModel):
    """Aggregate summary of a bulk session resume generation run."""

    session_id: int
    total_saved_jobs: int
    processed_count: int
    succeeded_count: int
    failed_count: int
    zip_download_url: str
    items: list[BulkExportJobItem] = Field(default_factory=list)


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
    cancelled: bool = False


class JobPatchRequest(BaseModel):
    """Update Keep/Discard disposition, application standing status, or notes on a job posting."""

    disposition: Optional[Literal["kept", "discarded"]] = None
    application_status: Optional[ApplicationStatusLiteral] = None
    application_notes: Optional[str] = None


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


class AppliedJobSummaryItem(BaseModel):
    """Application standing entry surfaced in the Reports tab and Excel export."""

    job_id: int
    session_id: Optional[int] = None
    session_name: str = ""
    company: str
    title: str
    location: str = ""
    role_track: str = "senior_swe"
    role_label: str = "Senior Software Engineer"
    application_status: str = "applied"
    status_label: str = "Applied"
    applied_at: Optional[datetime] = None
    application_notes: str = ""
    base_score: Optional[float] = None
    tailored_score: Optional[float] = None
    latest_run_id: Optional[int] = None
    latest_files: list[str] = Field(default_factory=list)
    url: Optional[str] = None


class AnalyticsReportResponse(BaseModel):
    """Workspace or session analytics metrics backing the interactive UI, HTML dashboard & Excel report."""

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
    total_applied: int = 0
    interviewing_count: int = 0
    offer_count: int = 0
    avg_tailored_score: float = 0.0
    avg_ats_lift: float = 0.0
    by_location: list[ReportBucketItem] = Field(default_factory=list)
    by_role: list[ReportBucketItem] = Field(default_factory=list)
    by_company: list[ReportBucketItem] = Field(default_factory=list)
    by_domain: list[ReportBucketItem] = Field(default_factory=list)
    by_posted_freshness: list[ReportBucketItem] = Field(default_factory=list)
    funnel_stages: list[ReportBucketItem] = Field(default_factory=list)
    by_source: list[ReportBucketItem] = Field(default_factory=list)
    by_currency: list[ReportBucketItem] = Field(default_factory=list)
    by_status: list[ReportBucketItem] = Field(default_factory=list)
    by_filter_reason: list[ReportBucketItem] = Field(default_factory=list)
    top_missing_skills: list[SessionSkillGapItem] = Field(default_factory=list)
    applied_jobs: list[AppliedJobSummaryItem] = Field(default_factory=list)
    html_report_path: Optional[str] = None


class TailorSectionRequest(BaseModel):
    """Request to regenerate/tailor a single section using a custom prompt and chosen engine."""

    job_id: int
    resume_id: Optional[int] = None
    section: Literal["summary", "experience", "projects", "skills", "education"]
    current_resume: CanonicalResume
    prompt: str = Field(default="", max_length=2000)
    engine: Literal["ollama", "claude", "fallback_script"] = "ollama"
    model: Optional[str] = None
    avoided_words: Optional[list[str]] = None
    bullets_per_experience: Optional[int] = Field(default=None, ge=2, le=12)
    bullets_per_project: Optional[int] = Field(default=None, ge=1, le=8)
    page_budget: Optional[float] = Field(default=None, ge=1.0, le=4.0)


class TailorSectionResponse(BaseModel):
    """Updated CanonicalResume and live ATS score after per-section prompt tailoring."""

    job_id: int
    resume_id: int
    section: Literal["summary", "experience", "projects", "skills"]
    engine_used: Literal["ollama_llm", "fallback_script"]
    model_used: Optional[str] = None
    updated_resume: CanonicalResume
    tailored_score: float
    tailored_report: ATSReport
    added_jd_skills: list[str] = Field(default_factory=list)
    notice: Optional[str] = None


class SkillsGraphJobNode(BaseModel):
    """Job node in the Role x Domain x Skills interactive knowledge graph."""

    id: str
    job_id: int
    title: str
    company: str
    location: str = ""
    role_track: str
    role_label: str
    domain: str
    relevance_score: float = 0.0
    skill_count: int = 0
    skills: list[str] = Field(default_factory=list)


class SkillsGraphSkillNode(BaseModel):
    """Skill node connecting required JD competencies across jobs and domains."""

    id: str
    keyword: str
    tier: str
    priority_label: str
    demand_count: int
    demand_pct: float
    covered_by_resumes: list[str] = Field(default_factory=list)
    is_covered: bool = False
    domains: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    role_tracks: list[str] = Field(default_factory=list)
    job_ids: list[int] = Field(default_factory=list)


class SkillsGraphEdge(BaseModel):
    """Directed/undirected relationship linking Job <-> Domain <-> Skill."""

    source: str
    target: str
    kind: Literal["job_domain", "job_skill", "domain_skill"]
    weight: float = 1.0
    tier: str = "important_systems"


class SkillsGraphDomainSummary(BaseModel):
    """Aggregated domain slice grouping companies, role tracks, and top demanded skills."""

    domain: str
    job_count: int
    companies: list[str] = Field(default_factory=list)
    role_tracks: list[str] = Field(default_factory=list)
    top_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)


class SkillsGraphResponse(BaseModel):
    """Complete interactive skills graph payload built from active session postings."""

    session_id: Optional[int] = None
    session_name: str
    total_jobs: int = 0
    total_skills: int = 0
    covered_skills: int = 0
    missing_skills: int = 0
    jobs: list[SkillsGraphJobNode] = Field(default_factory=list)
    skills: list[SkillsGraphSkillNode] = Field(default_factory=list)
    edges: list[SkillsGraphEdge] = Field(default_factory=list)
    domains: list[SkillsGraphDomainSummary] = Field(default_factory=list)


class ScrapeProgressResponse(BaseModel):
    """Live progress state for an in-flight or recently completed batch scrape."""

    session_id: int
    status: Literal["idle", "running", "completed", "cancelled", "failed"] = "idle"
    phase: str = ""
    current_source: str = ""
    steps_completed: int = 0
    steps_total: int = 0
    scanned_count: int = 0
    processed_count: int = 0
    saved_count: int = 0
    filtered_count: int = 0
    duplicate_skipped_count: int = 0
    filter_breakdown: dict[str, int] = Field(default_factory=dict)
    source_notes: list[str] = Field(default_factory=list)
    result: Optional[ScrapeBatchResult] = None
    error: Optional[str] = None


class FlushDataRequest(BaseModel):
    """Granular or master workspace flush request (master_flush preserves resumes)."""

    master_flush: bool = False
    flush_sessions_and_jobs: bool = False
    flush_tailoring_runs: bool = False
    flush_seen_history: bool = False
    seen_scope: Literal["all", "discarded", "auto_filtered"] = "all"
    flush_output_files: bool = False
    flush_resumes: bool = False


class FlushDataResult(BaseModel):
    """Counts of deleted records and cleaned artifacts after a flush."""

    sessions_deleted: int = 0
    jobs_deleted: int = 0
    tailoring_runs_deleted: int = 0
    seen_deleted: int = 0
    resumes_deleted: int = 0
    output_items_deleted: int = 0


class SessionFilteredJobResponse(BaseModel):
    """Audit item representing an auto-filtered or seen/skipped posting in a session."""

    id: int
    session_id: int
    url: str
    url_hash: str
    title: str
    company: str
    source: str
    location: str
    role_track: str
    category: Literal["auto_filtered", "seen_skipped"]
    filter_reason: str
    reason_label: str
    filter_reasons: list[str] = Field(default_factory=list)
    reason_labels: list[str] = Field(default_factory=list)
    suitability_notes: list[str] = Field(default_factory=list)
    posted_at: Optional[datetime] = None
    raw_text_preview: str = ""
    promoted_job_id: Optional[int] = None
    created_at: datetime


class PromoteFilteredJobsRequest(BaseModel):
    """Promote selected filtered/seen-skipped postings into the session's Saved Jobs list."""

    filtered_ids: list[int] = Field(min_length=1)
    role_track_override: Optional[str] = None


class RestoreDiscardedJobsRequest(BaseModel):
    """Restore selected discarded postings in a session back to Kept/Saved status."""

    job_ids: list[int] = Field(min_length=1)


class PromoteJobsResult(BaseModel):
    """Outcome summary after promoting filtered/seen or discarded jobs into Saved Jobs."""

    session_id: int
    added_count: int = 0
    already_saved_count: int = 0
    failed_count: int = 0
    saved_jobs: list[JobPostingResponse] = Field(default_factory=list)


class DraftScoreRequest(BaseModel):
    """Score an in-progress edited CanonicalResume draft live against a stored job posting."""

    job_id: int
    resume_id: Optional[int] = None
    draft_resume: CanonicalResume


class HumanizeResumeRequest(BaseModel):
    """Run the anti-AI-slop & recruiter XYZ humanizer pass on a draft CanonicalResume."""

    resume: CanonicalResume
    job_id: Optional[int] = None
    use_llm: bool = False
    avoided_words: Optional[list[str]] = None


class HumanizeResumeResponse(BaseModel):
    """Humanized CanonicalResume plus audit summary of changes applied."""

    resume: CanonicalResume
    changes_count: int = 0
    notes: list[str] = Field(default_factory=list)
    mode: Literal["deterministic", "ollama_llm"] = "deterministic"
    model_used: Optional[str] = None

