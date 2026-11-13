export type TabId = "sessions" | "reports" | "skills_graph" | "resume" | "config" | "logs";

export interface ActivityLogEntry {
  id: string;
  timestamp: string;
  level: "error" | "warning" | "info" | "success";
  source: string;
  title: string;
  message: string;
  details?: string;
  read?: boolean;
}

export interface ConfigOption {
  value: string | number | boolean;
  label: string;
  description?: string;
}

export type FieldType = "select" | "multi_select" | "number" | "text" | "boolean" | "tags";

export interface ConfigFieldSchema {
  key: string;
  label: string;
  description: string;
  field_type: FieldType;
  required: boolean;
  options: ConfigOption[];
  current_value: unknown;
  is_missing: boolean;
}

export interface AppSettingsValues {
  target_role_tracks: string[];
  target_locations: string[];
  work_types: ("remote" | "hybrid" | "onsite")[];
  job_types: ("full-time" | "contract")[];
  work_authorization: "h1b" | "any" | "us_citizen_gc_only";
  posted_within_default: "1h" | "12h" | "24h" | "7d" | "any";
  llm_mode: "off" | "ollama_local" | "ollama_docker" | null;
  llm_model: string;
  ollama_base_url: string;
  export_formats: ("pdf" | "docx")[];
  page_budget: number;
  default_bullets_per_role: number;
  avoided_ai_words: string[];
  custom_tailor_instructions: string;
  target_yoe_min: number | null;
  target_yoe_max: number | null;
  target_salary_min: number | null;
  min_hourly_rate: number | null;
  min_relevance_score: number;
  scraper_sources: ("greenhouse" | "lever" | "ashby" | "linkedin")[];
  company_boards: string[];
  title_blocklist: string[];
  resume_filename_format: string;
  strict_humanizer_gate: boolean;
  output_dir: string;
}

export interface ConfigResponse {
  values: AppSettingsValues;
  fields: ConfigFieldSchema[];
  missing_defaults: string[];
  needs_setup: boolean;
  last_modified_ns: number;
  config_path: string;
}

export interface RoleTrackConfig {
  id: string;
  display_name: string;
  category?: string;
  typical_yoe_label?: string;
  search_query?: string;
  company_examples?: string[];
  aliases: string[];
  description: string;
  target_yoe_range: number[];
  weights: Record<string, number>;
  keywords: Record<string, string[]>;
}

export interface ContactInfo {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  linkedin: string;
  github: string;
  portfolio: string;
}

export interface EducationItem {
  institution: string;
  degree: string;
  location: string;
  graduation_date: string;
  gpa?: string | null;
  coursework: string[];
}

export interface ExperienceBullet {
  id: string;
  text: string;
  provenance: "VERIFIED_BASE" | "BANK_PULLED" | "REFRAMED" | "SUGGESTED_DRAFT";
  approved: boolean;
  tags: string[];
}

export interface ExperienceItem {
  id: string;
  company: string;
  title: string;
  location: string;
  start_date: string;
  end_date: string;
  bullets: ExperienceBullet[];
}

export interface ProjectItem {
  id: string;
  name: string;
  tech_stack: string[];
  link: string;
  bullets: ExperienceBullet[];
}

export interface SkillCategory {
  category: string;
  items: string[];
}

export interface CertificationItem {
  name: string;
  issuer: string;
  date: string;
  credential_url: string;
}

export interface CanonicalResume {
  contact: ContactInfo;
  education: EducationItem[];
  experience: ExperienceItem[];
  projects: ProjectItem[];
  certifications: CertificationItem[];
  skills: SkillCategory[];
  summary?: string | null;
}

export interface ResumeRecordResponse {
  id: number;
  name: string;
  role_track: string;
  is_base: boolean;
  source_type: string;
  source_filename?: string | null;
  content: CanonicalResume;
  raw_text: string;
  created_at: string;
  updated_at: string;
}

export interface ResumeListResponse {
  has_base_resume: boolean;
  base_resume_id: number | null;
  base_by_role: Record<string, number>;
  resumes: ResumeRecordResponse[];
}

export interface WeightedSkill {
  keyword: string;
  tier: "core_must_have" | "important_systems" | "senior_leadership" | "bonus_nice_to_have";
  priority_label: string;
  weight: number;
  jd_mentions: number;
  in_required_section: boolean;
}

export interface SalaryInfo {
  min_amount?: number | null;
  max_amount?: number | null;
  currency: string;
  period: string;
  raw_snippet?: string | null;
  meets_target?: boolean | null;
}

export interface YoeInfo {
  min_years?: number | null;
  max_years?: number | null;
  raw_snippet?: string | null;
  fits_target_range?: boolean | null;
}

export interface JobAnalysis {
  company: string;
  title: string;
  location: string;
  role_track: string;
  salary: SalaryInfo;
  yoe: YoeInfo;
  weighted_skills: WeightedSkill[];
  expected_work: string[];
  detected_signals: string[];
  work_type: string;
  job_type: string;
  work_auth: string;
}

export type ApplicationStatus =
  | "ready"
  | "resume_created"
  | "applied"
  | "screening"
  | "interviewing"
  | "offer"
  | "rejected"
  | "skipped";
export type JobDisposition = "kept" | "discarded";

export interface JobPostingResponse {
  id: number;
  session_id?: number | null;
  url?: string | null;
  analysis: JobAnalysis;
  raw_text: string;
  source: string;
  posted_at?: string | null;
  work_type: string;
  job_type: string;
  work_auth: string;
  disposition: JobDisposition;
  application_status: ApplicationStatus;
  applied_at?: string | null;
  application_notes?: string;
  relevance_score: number;
  created_at: string;
}

export interface ScrapeSessionLocationCount {
  location: string;
  count: number;
}

export interface ScrapeSessionRoleCount {
  role_track: string;
  count: number;
}

export interface ScrapeSessionSummary {
  id: number;
  name: string;
  total_jobs: number;
  posted_within: string;
  scanned_count: number;
  saved_count: number;
  filtered_count: number;
  seen_skipped_count: number;
  discarded_count: number;
  filter_breakdown: Record<string, number>;
  source_notes: string[];
  locations: ScrapeSessionLocationCount[];
  roles: ScrapeSessionRoleCount[];
  currencies: string[];
  status_counts: Record<string, number>;
  sources_used: string[];
  created_at: string;
}

export interface FilteredJobSample {
  title: string;
  company: string;
  location: string;
  source: string;
  reason: string;
  url?: string | null;
}

export interface ScrapeBatchResult {
  session_id: number;
  posted_within: string;
  scanned_count: number;
  saved_count: number;
  filtered_count: number;
  duplicate_skipped_count: number;
  filter_breakdown: Record<string, number>;
  source_notes: string[];
  saved_jobs: JobPostingResponse[];
  filtered_samples: FilteredJobSample[];
  cancelled?: boolean;
}

export interface BulletDiagnostic {
  section: string;
  parent_name: string;
  bullet_text: string;
  has_strong_verb: boolean;
  has_quantified_metric: boolean;
  weak_phrases_found: string[];
  ai_slop_found: string[];
  exceeds_max_length: boolean;
}

export interface ATSReport {
  job_id: number;
  resume_id: number;
  overall_score: number;
  sub_scores: Record<string, number>;
  matched_skills: WeightedSkill[];
  missing_skills: WeightedSkill[];
  resume_skills?: string[];
  missing_requirements?: string[];
  bullet_diagnostics: BulletDiagnostic[];
  format_warnings: string[];
  estimated_pages: number;
}

export type TailorStrategy = "auto" | "ollama" | "claude" | "fallback_script";

export interface SanityCheckItem {
  check_id: string;
  title: string;
  status: "passed" | "repaired" | "warning";
  detail: string;
}

export interface TailoringReasoningStep {
  step: number;
  phase: string;
  decision: string;
}

export interface FieldChange {
  field_name: string;
  before: string;
  after: string;
  reason: string;
}

export interface BulletComparison {
  bullet_id: string;
  original_text: string;
  tailored_text: string;
  status: "unchanged" | "polished" | "reordered" | "edited";
  matched_keywords: string[];
  notes: string[];
}

export interface ExperienceComparison {
  experience_id: string;
  company: string;
  title: string;
  dates: string;
  bullets: BulletComparison[];
}

export interface TailorPreviewResponse {
  job_id: number;
  resume_id: number;
  resume_name: string;
  base_score: number;
  tailored_score: number;
  base_report: ATSReport;
  tailored_report: ATSReport;
  field_changes: FieldChange[];
  experience_comparisons: ExperienceComparison[];
  tailored_resume: CanonicalResume;
  tailor_mode?: "deterministic" | "fallback_script" | "ollama_llm";
  model_used?: string | null;
  humanized_count?: number;
  humanizer_notes?: string[];
  llm_notice?: string | null;
  added_jd_skills?: string[];
  target_score_met?: boolean;
  target_score_min?: number;
  target_score_max?: number;
  in_target_band?: boolean;
  bullets_per_experience?: number | null;
  bullets_per_role_counts?: number[];
  bullets_per_project?: number | null;
  page_budget?: number;
  reasoning_steps?: TailoringReasoningStep[];
  sanity_checks?: SanityCheckItem[];
  sanity_passed?: boolean;
  sanity_summary?: string;
}

export interface LlmStatusResponse {
  reachable: boolean;
  base_url: string;
  configured_model: string;
  model_installed: boolean;
  recommended_model?: string | null;
  available_models: string[];
  llm_mode?: string | null;
  error?: string | null;
}

export interface LlmTestResponse {
  ok: boolean;
  model: string;
  latency_ms: number;
  sample_output: string;
  error?: string | null;
}

export interface LlmBenchmarkItem {
  model: string;
  ok: boolean;
  latency_ms: number;
  json_valid: boolean;
  schema_complete: boolean;
  score: number;
  rank: number;
  notes: string;
  error?: string | null;
}

export interface LlmBenchmarkResponse {
  reachable: boolean;
  base_url: string;
  recommended_model?: string | null;
  items: LlmBenchmarkItem[];
}

export type ResumeSectionName = "summary" | "experience" | "projects" | "skills" | "education";

export interface TailorSectionRequest {
  job_id: number;
  resume_id?: number | null;
  section: ResumeSectionName;
  current_resume: CanonicalResume;
  prompt: string;
  engine: "ollama" | "claude" | "fallback_script";
  model?: string | null;
  avoided_words?: string[] | null;
  bullets_per_experience?: number | null;
  page_budget?: number | null;
}

export interface TailorSectionResponse {
  job_id: number;
  resume_id: number;
  section: ResumeSectionName;
  engine_used: "ollama_llm" | "claude" | "fallback_script";
  model_used?: string | null;
  updated_resume: CanonicalResume;
  tailored_score: number;
  tailored_report: ATSReport;
  added_jd_skills: string[];
  notice?: string | null;
}

export interface EditHistoryEntry {
  step: number;
  timestamp: string;
  action: string;
  detail: string;
  atsScore: number;
  engineLabel?: string;
  resumeSnapshot?: CanonicalResume;
}

export interface BootstrapEmployerInput {
  company: string;
  title?: string | null;
  location?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  bullets_count?: number | null;
}

export interface ResumeBootstrapRequest {
  full_name?: string;
  email?: string;
  phone?: string;
  location?: string;
  role_track?: string;
  years_experience?: number;
  focus_skills?: string[];
  employers?: BootstrapEmployerInput[];
  recent_company?: string | null;
  prior_company?: string | null;
  graduate_degree?: string | null;
  undergrad_degree?: string | null;
  bullets_per_experience?: number;
  bullets_per_role_counts?: number[] | null;
  projects_count?: number;
  page_budget?: number;
  job_id?: number | null;
  use_llm?: boolean;
  save_as_base?: boolean;
  resume_name?: string | null;
}

export interface BulkExportRequest {
  resume_id?: number | null;
  formats?: ("pdf" | "docx")[];
  tailor_strategy?: TailorStrategy;
  adapt_location?: boolean;
  auto_size?: boolean;
  target_score_min?: number;
  target_score_max?: number;
  include_already_created?: boolean;
  max_jobs?: number | null;
  avoided_words?: string[] | null;
  custom_instructions?: string | null;
  target_sections?: string[] | null;
}

export interface BulkExportJobItem {
  job_id: number;
  run_id: number;
  company: string;
  title: string;
  role_track: string;
  yoe_snippet?: string | null;
  base_score: number;
  tailored_score: number;
  score_delta?: number;
  in_target_band: boolean;
  page_budget: number;
  bullets_per_role_counts: number[];
  tailor_mode: "fallback_script" | "deterministic" | "ollama_llm";
  sanity_passed: boolean;
  generated_files: string[];
  tailored_resume?: CanonicalResume | null;
  tailored_report?: ATSReport | null;
  export_result?: ExportResponse | null;
  error?: string | null;
}

export interface BulkExportResponse {
  session_id: number;
  total_saved_jobs: number;
  processed_count: number;
  succeeded_count: number;
  failed_count: number;
  zip_download_url: string;
  items: BulkExportJobItem[];
}

export interface ResumeBootstrapResponse {
  resume: ResumeRecordResponse;
  generation_mode: "ollama_llm" | "deterministic_template";
  model_used?: string | null;
  humanized_count: number;
  notes: string[];
}

export interface HumanizeResumeResponse {
  resume: CanonicalResume;
  changes_count: number;
  notes: string[];
  mode: "deterministic" | "ollama_llm";
  model_used?: string | null;
}

export interface ExportResponse {
  run_id: number;
  job_id: number;
  resume_id: number;
  ats_score: number;
  output_folder: string;
  folder_name: string;
  generated_files: string[];
  pdf_text_verified?: boolean | null;
  report: ATSReport;
}

export interface ExportRunItem {
  run_id: number;
  job_id: number;
  resume_id: number;
  base_score: number;
  tailored_score: number;
  output_folder: string;
  folder_name: string;
  files: string[];
  created_at: string;
}

export interface SessionSkillGapItem {
  keyword: string;
  tier: string;
  priority_label: string;
  demand_count: number;
  demand_pct: number;
  covered_by_resumes: string[];
  is_covered: boolean;
}

export interface RoleGapBreakdown {
  role_track: string;
  job_count: number;
  has_base_resume: boolean;
  avg_relevance: number;
  top_missing_skills: SessionSkillGapItem[];
  top_matched_skills: SessionSkillGapItem[];
}

export interface SessionSkillsGapResponse {
  session_id?: number | null;
  session_name: string;
  total_active_jobs: number;
  covered_skill_count: number;
  missing_skill_count: number;
  overall_missing: SessionSkillGapItem[];
  overall_strengths: SessionSkillGapItem[];
  by_role: RoleGapBreakdown[];
}

export interface ReportBucketItem {
  label: string;
  count: number;
  pct: floatOrNumber;
}

type floatOrNumber = number;

export interface AppliedJobSummaryItem {
  job_id: number;
  session_id?: number | null;
  session_name: string;
  company: string;
  title: string;
  location: string;
  role_track: string;
  role_label: string;
  application_status: ApplicationStatus;
  status_label: string;
  applied_at?: string | null;
  application_notes: string;
  base_score?: number | null;
  tailored_score?: number | null;
  latest_run_id?: number | null;
  latest_files: string[];
  url?: string | null;
}

export interface AnalyticsReportResponse {
  generated_at: string;
  session_id?: number | null;
  session_name: string;
  total_sessions: number;
  total_scanned: number;
  total_saved: number;
  total_filtered: number;
  total_discarded: number;
  seen_ledger_count: number;
  omitted_salary_count: number;
  avg_relevance_score: number;
  total_exports: number;
  total_applied?: number;
  interviewing_count?: number;
  offer_count?: number;
  avg_tailored_score?: number;
  avg_ats_lift?: number;
  by_location: ReportBucketItem[];
  by_role: ReportBucketItem[];
  by_company?: ReportBucketItem[];
  by_domain?: ReportBucketItem[];
  by_posted_freshness?: ReportBucketItem[];
  funnel_stages?: ReportBucketItem[];
  by_source: ReportBucketItem[];
  by_currency: ReportBucketItem[];
  by_status: ReportBucketItem[];
  by_filter_reason: ReportBucketItem[];
  top_missing_skills: SessionSkillGapItem[];
  applied_jobs?: AppliedJobSummaryItem[];
  html_report_path?: string | null;
}

export interface SkillsGraphJobNode {
  id: string;
  job_id: number;
  title: string;
  company: string;
  location: string;
  role_track: string;
  role_label: string;
  domain: string;
  relevance_score: number;
  skill_count: number;
  skills: string[];
}

export interface SkillsGraphSkillNode {
  id: string;
  keyword: string;
  tier: string;
  priority_label: string;
  demand_count: number;
  demand_pct: number;
  covered_by_resumes: string[];
  is_covered: boolean;
  domains: string[];
  companies: string[];
  role_tracks: string[];
  job_ids: number[];
}

export interface SkillsGraphEdge {
  source: string;
  target: string;
  kind: "job_domain" | "job_skill" | "domain_skill";
  weight: number;
  tier: string;
}

export interface SkillsGraphDomainSummary {
  domain: string;
  job_count: number;
  companies: string[];
  role_tracks: string[];
  top_skills: string[];
  missing_skills: string[];
}

export interface SkillsGraphResponse {
  session_id?: number | null;
  session_name: string;
  total_jobs: number;
  total_skills: number;
  covered_skills: number;
  missing_skills: number;
  jobs: SkillsGraphJobNode[];
  skills: SkillsGraphSkillNode[];
  edges: SkillsGraphEdge[];
  domains: SkillsGraphDomainSummary[];
}

export interface LocationCatalogResponse {
  top_20: string[];
  other_us: string[];
  all_us: string[];
}

export interface ScrapeProgressResponse {
  session_id: number;
  status: "idle" | "running" | "completed" | "cancelled" | "failed";
  phase: string;
  current_source: string;
  steps_completed: number;
  steps_total: number;
  scanned_count: number;
  processed_count: number;
  saved_count: number;
  filtered_count: number;
  duplicate_skipped_count: number;
  filter_breakdown: Record<string, number>;
  source_notes: string[];
  result?: ScrapeBatchResult | null;
  error?: string | null;
}

export interface FlushDataRequest {
  master_flush?: boolean;
  flush_sessions_and_jobs?: boolean;
  flush_tailoring_runs?: boolean;
  flush_seen_history?: boolean;
  seen_scope?: "all" | "discarded" | "auto_filtered";
  flush_output_files?: boolean;
  flush_resumes?: boolean;
}

export interface FlushDataResult {
  sessions_deleted: number;
  jobs_deleted: number;
  tailoring_runs_deleted: number;
  seen_deleted: number;
  resumes_deleted: number;
  output_items_deleted: number;
}

export interface SessionFilteredJobResponse {
  id: number;
  session_id: number;
  url: string;
  url_hash: string;
  title: string;
  company: string;
  source: string;
  location: string;
  role_track: string;
  category: "auto_filtered" | "seen_skipped";
  filter_reason: string;
  reason_label: string;
  filter_reasons: string[];
  reason_labels: string[];
  suitability_notes: string[];
  posted_at?: string | null;
  raw_text_preview: string;
  promoted_job_id?: number | null;
  created_at: string;
}

export interface PromoteJobsResult {
  session_id: number;
  added_count: number;
  already_saved_count: number;
  failed_count: number;
  saved_jobs: JobPostingResponse[];
}
