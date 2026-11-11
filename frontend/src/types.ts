export type TabId = "sessions" | "skills_gap" | "reports" | "resume" | "config";

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
  llm_mode: "off" | "ollama_docker" | null;
  llm_model: string;
  ollama_base_url: string;
  export_formats: ("pdf" | "docx")[];
  page_budget: number;
  target_yoe_min: number;
  target_yoe_max: number;
  target_salary_min: number | null;
  min_hourly_rate: number | null;
  min_relevance_score: number;
  scraper_sources: ("greenhouse" | "lever" | "linkedin")[];
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

export type ApplicationStatus = "ready" | "resume_created" | "applied" | "skipped";
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
  filter_breakdown: Record<string, number>;
  source_notes: string[];
  locations: ScrapeSessionLocationCount[];
  roles: ScrapeSessionRoleCount[];
  currencies: string[];
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
  bullet_diagnostics: BulletDiagnostic[];
  format_warnings: string[];
  estimated_pages: number;
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
  by_location: ReportBucketItem[];
  by_role: ReportBucketItem[];
  by_source: ReportBucketItem[];
  by_currency: ReportBucketItem[];
  by_status: ReportBucketItem[];
  by_filter_reason: ReportBucketItem[];
  top_missing_skills: SessionSkillGapItem[];
  html_report_path?: string | null;
}
