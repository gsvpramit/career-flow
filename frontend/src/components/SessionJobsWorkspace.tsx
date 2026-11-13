import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { api } from "../api";
import {
  BULLET_COUNT_OPTIONS,
  buildAvoidedWordsGroups,
  createDefaultEmployers,
  DEFAULT_AVOIDED_AI_WORDS,
  formatJobTypeLabel,
  formatSourceLabel,
  formatStatusLabel,
  formatWorkTypeLabel,
} from "../constants/tailoring";
import { LiveResumeSheet } from "./LiveResumeSheet";
import { CandidateBulletBankModal } from "./CandidateBulletBankModal";
import { MultiSelectCheckboxDropdown } from "./MultiSelectCheckboxDropdown";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import { formatEasternDateTime, formatPostedAtEastern } from "../utils/datetime";
import {
  decodeHtmlText,
  extractAllPostingSkills,
  parseJdIntoBlocks,
} from "../utils/jdFormatter";
import type {
  ApplicationStatus,
  ATSReport,
  BootstrapEmployerInput,
  BulkExportResponse,
  CanonicalResume,
  ConfigResponse,
  EditHistoryEntry,
  ExportResponse,
  JobPostingResponse,
  LlmStatusResponse,
  ResumeListResponse,
  ResumeSectionName,
  RoleTrackConfig,
  ScrapeSessionSummary,
  SessionFilteredJobResponse,
  TabId,
  TailorPreviewResponse,
  TailorStrategy,
} from "../types";

interface SessionJobsWorkspaceProps {
  session: ScrapeSessionSummary;
  config?: ConfigResponse | null;
  jobs: JobPostingResponse[];
  discardedJobs: JobPostingResponse[];
  filteredItems: SessionFilteredJobResponse[];
  loadingJobs: boolean;
  roleTracks: RoleTrackConfig[];
  resumeState: ResumeListResponse | null;
  onJobsUpdated: () => Promise<void>;
  onResumesChanged?: () => Promise<void>;
  onNavigateTab: (tab: TabId) => void;
  viewportMode?: "standard" | "wide" | "maximized";
  onChangeViewportMode?: (mode: "standard" | "wide" | "maximized") => void;
}

type WorkspaceViewMode = "saved" | "filtered" | "seen" | "discarded";
type SavedSortMode =
  | "latest"
  | "similar_selected"
  | "match_score"
  | "company_open_roles"
  | "salary_high"
  | "oldest"
  | "company_az"
  | "title_az";
type AuditSortMode =
  | "latest_posted"
  | "most_reasons"
  | "logged_recent"
  | "company_az"
  | "title_az";
type DiscardedSortMode = "latest" | "company_az" | "title_az";

const STATUS_BADGE_CLASS: Record<ApplicationStatus, string> = {
  ready: "pill",
  resume_created: "pill pill-blue",
  applied: "pill pill-green",
  screening: "pill pill-blue",
  interviewing: "pill pill-green",
  offer: "pill pill-green",
  rejected: "pill pill-red",
  skipped: "pill pill-amber",
};

interface JobProgressState {
  visited?: boolean;
  tailored?: boolean;
  downloaded?: boolean;
  lastScore?: number;
  updatedAt?: string;
}

interface JobDraftSnapshot {
  resumeId: number | null;
  scoreReport: ATSReport | null;
  tailorPreview: TailorPreviewResponse;
  editedResume: CanonicalResume;
  exportResult: ExportResponse | null;
  editHistory?: EditHistoryEntry[];
  tailorStrategy?: TailorStrategy;
  pageBudget?: number;
  targetSections?: string[];
  autoSize?: boolean;
  customRoleBulletCounts?: number[];
  bulletsPerProject?: number | "";
}

const JOB_PROGRESS_STORAGE_KEY = "careerflow.jobProgress.v1";

function loadJobProgressMap(): Record<number, JobProgressState> {
  try {
    const raw = window.localStorage.getItem(JOB_PROGRESS_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, JobProgressState>;
    const out: Record<number, JobProgressState> = {};
    for (const [k, v] of Object.entries(parsed)) {
      const id = Number(k);
      if (Number.isFinite(id) && v && typeof v === "object") {
        out[id] = v;
      }
    }
    return out;
  } catch {
    return {};
  }
}

function saveJobProgressMap(map: Record<number, JobProgressState>): void {
  try {
    window.localStorage.setItem(JOB_PROGRESS_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // ignore
  }
}

const DRAFT_STORAGE_PREFIX = "careerflow.jobDraft.v2.";

function loadJobDraft(jobId: number): JobDraftSnapshot | null {
  try {
    const raw = window.localStorage.getItem(`${DRAFT_STORAGE_PREFIX}${jobId}`);
    if (!raw) return null;
    return JSON.parse(raw) as JobDraftSnapshot;
  } catch {
    return null;
  }
}

function saveJobDraft(jobId: number, draft: JobDraftSnapshot): void {
  try {
    window.localStorage.setItem(`${DRAFT_STORAGE_PREFIX}${jobId}`, JSON.stringify(draft));
  } catch {
    // ignore quota errors
  }
}

function computeJobStage(job: JobPostingResponse, prog?: JobProgressState) {
  if (job.application_status === "rejected") {
    return {
      stepCount: 4,
      label: formatStatusLabel(job.application_status),
      pillClass: STATUS_BADGE_CLASS[job.application_status],
      segClass: "pending",
      isPendingDownload: false,
    };
  }
  if (
    job.application_status === "applied" ||
    job.application_status === "screening" ||
    job.application_status === "interviewing" ||
    job.application_status === "offer"
  ) {
    return {
      stepCount: 4,
      label: formatStatusLabel(job.application_status),
      pillClass: STATUS_BADGE_CLASS[job.application_status],
      segClass: "complete",
      isPendingDownload: false,
    };
  }
  if (prog?.downloaded || job.application_status === "resume_created") {
    return {
      stepCount: 3,
      label: "Resume Downloaded",
      pillClass: "pill pill-green",
      segClass: "complete",
      isPendingDownload: false,
    };
  }
  if (prog?.tailored) {
    return {
      stepCount: 2,
      label: "Tailored · Download Pending",
      pillClass: "pill pill-amber",
      segClass: "pending",
      isPendingDownload: true,
    };
  }
  if (prog?.visited) {
    return {
      stepCount: 1,
      label: "Visited",
      pillClass: "pill pill-blue",
      segClass: "done",
      isPendingDownload: false,
    };
  }
  return {
    stepCount: 0,
    label: formatStatusLabel(job.application_status),
    pillClass: STATUS_BADGE_CLASS[job.application_status],
    segClass: "",
    isPendingDownload: false,
  };
}

const STOP_TITLE_TOKENS = new Set([
  "the",
  "and",
  "for",
  "with",
  "of",
  "in",
  "at",
  "to",
  "or",
  "on",
  "an",
]);

function parsePostingMs(postedAt?: string | null, fallbackCreatedAt?: string | null): number {
  if (postedAt) {
    const ms = Date.parse(postedAt);
    if (Number.isFinite(ms)) return ms;
  }
  if (fallbackCreatedAt) {
    const ms = Date.parse(fallbackCreatedAt);
    if (Number.isFinite(ms)) return ms;
  }
  return 0;
}

function normalizeTitleTokens(title: string): Set<string> {
  const words = title
    .toLowerCase()
    .replace(/[^a-z0-9+#.\s]/g, " ")
    .split(/\s+/)
    .filter((w) => w.length >= 2 && !STOP_TITLE_TOKENS.has(w));
  return new Set(words);
}

function computeSimilarityPercent(
  job: JobPostingResponse,
  anchor: JobPostingResponse | null
): number {
  if (!anchor) return Math.round(job.relevance_score);
  if (job.id === anchor.id) return 100;

  let score = 0;
  if (job.analysis.role_track === anchor.analysis.role_track) {
    score += 35;
  }

  const anchorSkills = new Set(
    (anchor.analysis.weighted_skills ?? []).map((s) => s.keyword.toLowerCase())
  );
  const jobSkills = new Set(
    (job.analysis.weighted_skills ?? []).map((s) => s.keyword.toLowerCase())
  );
  if (anchorSkills.size > 0 && jobSkills.size > 0) {
    let overlap = 0;
    for (const sk of jobSkills) {
      if (anchorSkills.has(sk)) overlap += 1;
    }
    const union = new Set([...anchorSkills, ...jobSkills]).size;
    if (union > 0) {
      score += Math.round((overlap / union) * 40);
    }
  }

  const anchorTokens = normalizeTitleTokens(anchor.analysis.title);
  const jobTokens = normalizeTitleTokens(job.analysis.title);
  if (anchorTokens.size > 0 && jobTokens.size > 0) {
    let overlap = 0;
    for (const tok of jobTokens) {
      if (anchorTokens.has(tok)) overlap += 1;
    }
    const union = new Set([...anchorTokens, ...jobTokens]).size;
    if (union > 0) {
      score += Math.round((overlap / union) * 20);
    }
  }

  if (job.work_type !== "unspecified" && job.work_type === anchor.work_type) {
    score += 5;
  }
  return Math.min(99, Math.max(0, score));
}

function effectiveAnnualComp(job: JobPostingResponse): number {
  const s = job.analysis.salary;
  if (s.min_amount == null) return -1;
  const amount = s.max_amount ?? s.min_amount;
  return s.period === "hour" ? amount * 2080 : amount;
}

function formatCompensation(job: JobPostingResponse): string {
  const s = job.analysis.salary;
  if (s.min_amount == null) return "Salary not listed";
  const prefix = s.currency === "USD" ? "$" : `${s.currency} `;
  const unit = s.period === "hour" ? "/hr" : "";
  if (s.max_amount && s.max_amount !== s.min_amount) {
    return `${prefix}${s.min_amount.toLocaleString()}–${prefix}${s.max_amount.toLocaleString()}${unit}`;
  }
  return `${prefix}${s.min_amount.toLocaleString()}${unit}`;
}

function evaluateJobSuitability(
  job: JobPostingResponse,
  scoreReport: ATSReport | null,
  config: ConfigResponse | null | undefined,
  originAudit: SessionFilteredJobResponse | null,
  trackLabelFn: (id: string) => string
): string[] {
  const reasons: string[] = [];
  const cfg = config?.values;

  if (originAudit?.suitability_notes?.length) {
    for (const note of originAudit.suitability_notes) {
      reasons.push(`Previously flagged during scrape: ${note}`);
    }
  }

  const loc = (job.analysis.location || "").trim();
  const locLower = loc.toLowerCase();
  const targetLocs = cfg?.target_locations ?? [];
  if (!loc) {
    reasons.push("Location is unspecified in posting — confirm US work eligibility.");
  } else if (targetLocs.length > 0 && !targetLocs.includes("ALL_US")) {
    const matchesLoc = targetLocs.some((t) => {
      const tl = t.toLowerCase();
      if (tl === "remote") return locLower.includes("remote");
      return locLower.includes(tl.split(",")[0].trim());
    });
    if (!matchesLoc && !(job.work_type === "remote" && targetLocs.includes("Remote"))) {
      const preview = targetLocs.slice(0, 3).join(", ");
      const suffix = targetLocs.length > 3 ? ` (+${targetLocs.length - 3} more)` : "";
      reasons.push(`Location "${loc}" is outside your target cities (${preview}${suffix}).`);
    }
  }

  const userAuth = cfg?.work_authorization;
  if (job.analysis.work_auth === "no_sponsorship" && (!userAuth || userAuth === "h1b")) {
    reasons.push("No visa sponsorship / US Citizen or Green Card required.");
  } else if (userAuth === "h1b" && job.analysis.work_auth === "unknown") {
    reasons.push("H-1B sponsorship is not explicitly confirmed in the posting.");
  }

  const yoe = job.analysis.yoe;
  if (yoe.fits_target_range === false) {
    const rangeStr =
      yoe.min_years != null
        ? yoe.max_years != null
          ? `${yoe.min_years}–${yoe.max_years} yrs`
          : `${yoe.min_years}+ yrs`
        : "stated experience";
    reasons.push(`Required experience (${rangeStr}) falls outside your target YOE window.`);
  } else {
    if (cfg?.target_yoe_max != null && yoe.min_years != null && yoe.min_years > cfg.target_yoe_max) {
      reasons.push(
        `Requires ${yoe.min_years}+ years of experience, above your configured max (${cfg.target_yoe_max} yrs).`
      );
    }
    if (cfg?.target_yoe_min != null && yoe.max_years != null && yoe.max_years < cfg.target_yoe_min) {
      reasons.push(
        `Targets up to ${yoe.max_years} years of experience, below your configured min (${cfg.target_yoe_min} yrs).`
      );
    }
  }

  if (job.analysis.salary.meets_target === false) {
    reasons.push(
      `Listed compensation (${formatCompensation(job)}) is below your target minimum.`
    );
  } else if (job.analysis.salary.min_amount != null && cfg) {
    const ceiling = job.analysis.salary.max_amount ?? job.analysis.salary.min_amount;
    if (job.analysis.salary.period === "hour" && cfg.min_hourly_rate != null && ceiling < cfg.min_hourly_rate) {
      reasons.push(
        `Hourly pay (${formatCompensation(job)}) is below your $${cfg.min_hourly_rate}/hr minimum.`
      );
    } else if (
      job.analysis.salary.period !== "hour" &&
      cfg.target_salary_min != null &&
      ceiling < cfg.target_salary_min
    ) {
      reasons.push(
        `Annual salary (${formatCompensation(job)}) is below your $${cfg.target_salary_min.toLocaleString()} minimum.`
      );
    }
  }

  if (
    cfg?.work_types?.length &&
    job.work_type !== "unspecified" &&
    !cfg.work_types.includes(job.work_type as never)
  ) {
    reasons.push(
      `Work mode "${job.work_type}" differs from your config (${cfg.work_types.join(", ")}).`
    );
  }
  if (cfg?.job_types?.length && job.job_type && !cfg.job_types.includes(job.job_type as never)) {
    reasons.push(
      `Schedule type "${job.job_type}" differs from your config (${cfg.job_types.join(", ")}).`
    );
  }
  if (
    cfg?.target_role_tracks?.length &&
    !cfg.target_role_tracks.includes(job.analysis.role_track)
  ) {
    reasons.push(
      `Detected role track (${trackLabelFn(job.analysis.role_track)}) is outside your target role tracks.`
    );
  }
  if (cfg?.min_relevance_score != null && job.relevance_score < cfg.min_relevance_score) {
    reasons.push(
      `Job relevance score (${Math.round(job.relevance_score)}%) is below your ${Math.round(cfg.min_relevance_score)}% threshold.`
    );
  }
  if (cfg?.title_blocklist?.length) {
    const titleLower = job.analysis.title.toLowerCase();
    const blocked = cfg.title_blocklist.find((term) => term && titleLower.includes(term.toLowerCase()));
    if (blocked) {
      reasons.push(`Title contains blocklisted term "${blocked}".`);
    }
  }

  if (scoreReport) {
    if (scoreReport.overall_score < 60) {
      reasons.push(
        `Base resume ATS match is ${Math.round(scoreReport.overall_score)}% — needs tailoring before applying.`
      );
    }
    const coreMissing = scoreReport.missing_skills.filter(
      (s) => s.tier === "core_must_have" || s.tier === "important_systems"
    );
    if (coreMissing.length > 0) {
      const preview = coreMissing
        .slice(0, 6)
        .map((s) => s.keyword)
        .join(", ");
      const extra = coreMissing.length > 6 ? ` (+${coreMissing.length - 6} more)` : "";
      reasons.push(`Missing priority skills on selected resume: ${preview}${extra}.`);
    } else if (scoreReport.missing_skills.length > 0) {
      const preview = scoreReport.missing_skills
        .slice(0, 5)
        .map((s) => s.keyword)
        .join(", ");
      reasons.push(
        `Missing ${scoreReport.missing_skills.length} keyword(s) on selected resume: ${preview}.`
      );
    }
  }

  return Array.from(new Set(reasons));
}

export function SessionJobsWorkspace({
  session,
  config = null,
  jobs,
  discardedJobs,
  filteredItems,
  loadingJobs,
  roleTracks,
  resumeState,
  onJobsUpdated,
  onResumesChanged,
  onNavigateTab,
  viewportMode = "maximized",
  onChangeViewportMode,
}: SessionJobsWorkspaceProps) {
  const [workspaceView, setWorkspaceView] = useState<WorkspaceViewMode>("saved");
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [selectedCities, setSelectedCities] = useState<string[]>([]);
  const [companyFilter, setCompanyFilter] = useState<string>("all");
  const [postedWithinFilter, setPostedWithinFilter] = useState<
    "all" | "1h" | "6h" | "24h" | "3d" | "7d"
  >("all");
  const [roleFilter, setRoleFilter] = useState<string>("all");
  const [sourceFilter, setSourceFilter] = useState<string>("all");
  const [workTypeFilter, setWorkTypeFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [minMatchFilter, setMinMatchFilter] = useState<number>(0);
  const [onlyH1bConfirmed, setOnlyH1bConfirmed] = useState(false);
  const [onlyWithSalary, setOnlyWithSalary] = useState(false);
  const [sortBy, setSortBy] = useState<SavedSortMode>("latest");
  const [jobQuery, setJobQuery] = useState("");

  // Audit review (Filtered by Rules / Seen-Skipped / Discarded)
  const [auditReasonFilter, setAuditReasonFilter] = useState<string>("all");
  const [auditLocationFilter, setAuditLocationFilter] = useState<string>("all");
  const [auditSourceFilter, setAuditSourceFilter] = useState<string>("all");
  const [auditSortBy, setAuditSortBy] = useState<AuditSortMode>("latest_posted");
  const [discardedSortBy, setDiscardedSortBy] = useState<DiscardedSortMode>("latest");
  const [auditQuery, setAuditQuery] = useState("");
  const [selectedFilteredIds, setSelectedFilteredIds] = useState<number[]>([]);
  const [selectedDiscardedIds, setSelectedDiscardedIds] = useState<number[]>([]);
  const [promoteRoleOverride, setPromoteRoleOverride] = useState<string>("");
  const [promotingBusy, setPromotingBusy] = useState(false);

  const [selectedResumeId, setSelectedResumeId] = useState<number | null>(null);
  const selectedResume = useMemo(
    () => resumeState?.resumes.find((r) => r.id === selectedResumeId)?.content ?? null,
    [resumeState, selectedResumeId]
  );
  const [scoreReport, setScoreReport] = useState<ATSReport | null>(null);
  const [liveReport, setLiveReport] = useState<ATSReport | null>(null);
  const [tailorPreview, setTailorPreview] = useState<TailorPreviewResponse | null>(null);
  const [editedResume, setEditedResume] = useState<CanonicalResume | null>(null);
  const [adaptLocation, setAdaptLocation] = useState(true);
  const [exportResult, setExportResult] = useState<ExportResponse | null>(null);
  const [jdViewMode, setJdViewMode] = useState<"highlights" | "formatted" | "plain">("highlights");
  const [showAllSkills, setShowAllSkills] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [llmTailorBusy, setLlmTailorBusy] = useState(false);
  const [tailorStrategy, setTailorStrategy] = useState<TailorStrategy>("ollama");
  const [targetSections, setTargetSections] = useState<string[]>([
    "summary",
    "experience",
    "projects",
    "skills",
  ]);
  const [autoSize, setAutoSize] = useState(true);
  const [customRoleBulletCounts, setCustomRoleBulletCounts] = useState<number[]>([6, 6, 5]);
  const [showQuickBootstrap, setShowQuickBootstrap] = useState(false);
  const [bootName, setBootName] = useState("Alex Rivera");
  const [bootYears, setBootYears] = useState(5);
  const [bootLocation, setBootLocation] = useState("");
  const [bootRoleTrack, setBootRoleTrack] = useState("");
  const [bootFocusSkills, setBootFocusSkills] = useState("");
  const [bootEmployers, setBootEmployers] = useState<BootstrapEmployerInput[]>(() =>
    createDefaultEmployers()
  );
  const [bootGradDegree, setBootGradDegree] = useState("");
  const [bootUndergradDegree, setBootUndergradDegree] = useState("");
  const [bootProjectsCount, setBootProjectsCount] = useState(2);
  const [bootModeBusy, setBootModeBusy] = useState<"ollama" | "fallback" | null>(null);

  const [jobProgressMap, setJobProgressMap] = useState<Record<number, JobProgressState>>(() =>
    loadJobProgressMap()
  );
  const jobDraftsRef = useRef<Record<number, JobDraftSnapshot>>({});
  const prevSelectedJobIdRef = useRef<number | null>(null);
  const skipNextAutoScoreRef = useRef<boolean>(false);

  const [collapsedCards, setCollapsedCards] = useState<Record<string, boolean>>({
    responsibilities: true,
    resumesInHand: true,
    skillsGap: true,
    sanity: true,
  });
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkStrategy, setBulkStrategy] = useState<TailorStrategy>("auto");
  const [bulkAutoSize, setBulkAutoSize] = useState(true);
  const [bulkIncludeAlready, setBulkIncludeAlready] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkResult, setBulkResult] = useState<BulkExportResponse | null>(null);
  const [bulkError, setBulkError] = useState<string | null>(null);

  // Dynamic layout controls (Straight Split vs 4x4 Grid + measurements)
  const [jobsViewLayout, setJobsViewLayout] = useState<"split" | "grid">(() => {
    try {
      return window.localStorage.getItem("careerflow.jobsViewLayout") === "grid"
        ? "grid"
        : "split";
    } catch {
      return "split";
    }
  });
  const [splitLeftPct, setSplitLeftPct] = useState<number>(() => {
    try {
      const n = Number(window.localStorage.getItem("careerflow.splitLeftPct"));
      return Number.isFinite(n) && n >= 20 && n <= 55 ? n : 33;
    } catch {
      return 33;
    }
  });
  const [splitListHeightPx, setSplitListHeightPx] = useState<number>(() => {
    try {
      const n = Number(window.localStorage.getItem("careerflow.splitListHeightPx"));
      return Number.isFinite(n) && n >= 380 && n <= 1200 ? n : 760;
    } catch {
      return 760;
    }
  });
  const [gridCols, setGridCols] = useState<number>(() => {
    try {
      const n = Number(window.localStorage.getItem("careerflow.gridCols"));
      return Number.isFinite(n) && n >= 2 && n <= 5 ? n : 4;
    } catch {
      return 4;
    }
  });
  const [gridRows, setGridRows] = useState<number>(() => {
    try {
      const n = Number(window.localStorage.getItem("careerflow.gridRows"));
      return Number.isFinite(n) && (n >= 2 && n <= 99) ? n : 4;
    } catch {
      return 4;
    }
  });

  // Live Resume Tailoring Studio Controls
  const [bulletsPerExperience, setBulletsPerExperience] = useState<number | null>(
    config?.values.default_bullets_per_role ?? 5
  );
  const [pageBudget, setPageBudget] = useState<number>(config?.values.page_budget ?? 1.5);
  const [avoidedWords, setAvoidedWords] = useState<string[]>(
    config?.values.avoided_ai_words ?? [...DEFAULT_AVOIDED_AI_WORDS]
  );
  const [customInstructions, setCustomInstructions] = useState<string>(
    config?.values.custom_tailor_instructions ?? ""
  );
  const [bulletsPerProject, setBulletsPerProject] = useState<number | "">("");
  const [customAvoidedStudioWord, setCustomAvoidedStudioWord] = useState<string>("");
  const [showCustomPromptInput, setShowCustomPromptInput] = useState(false);
  const [studioSectionTab, setStudioSectionTab] = useState<
    "summary" | "experience" | "projects" | "skills" | "education"
  >("experience");
  const [sectionPrompts, setSectionPrompts] = useState<
    Record<ResumeSectionName, string>
  >({
    summary: "",
    experience: "",
    projects: "",
    skills: "",
    education: "",
  });
  const [sectionEngines, setSectionEngines] = useState<
    Record<ResumeSectionName, "ollama" | "claude">
  >({
    summary: "ollama",
    experience: "ollama",
    projects: "ollama",
    skills: "ollama",
    education: "ollama",
  });
  const [sectionBusy, setSectionBusy] = useState<ResumeSectionName | null>(null);
  const [sectionNotice, setSectionNotice] = useState<string | null>(null);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [sectionModelOverride, setSectionModelOverride] = useState<string>("");
  const [selectedStudioModel, setSelectedStudioModel] = useState<string>("");
  const [skillsAlignedJobs, setSkillsAlignedJobs] = useState<Record<number, boolean>>({});
  const [bulletBankTarget, setBulletBankTarget] = useState<{
    type: "exp" | "proj";
    expIdx?: number;
    projIdx?: number;
  } | null>(null);

  const existingResumeBullets = useMemo(() => {
    if (!editedResume) return [];
    const list: string[] = [];
    editedResume.experience?.forEach((e) => e.bullets?.forEach((b) => list.push(b.text)));
    editedResume.projects?.forEach((p) => p.bullets?.forEach((b) => list.push(b.text)));
    return list;
  }, [editedResume]);
  const [editHistoryByJob, setEditHistoryByJob] = useState<Record<number, EditHistoryEntry[]>>({});
  const lastManualEditRef = useRef<Record<string, number>>({});
  const [showDiffDrawer, setShowDiffDrawer] = useState(false);
  const [sectionEditorCollapsed, setSectionEditorCollapsed] = useState(true);
  const [tailorStepIndex, setTailorStepIndex] = useState(1);
  const [llmStatusInfo, setLlmStatusInfo] = useState<LlmStatusResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const llm = await api.getLlmStatus();
        if (active) {
          setLlmStatusInfo(llm);
          if (llm.available_models?.length) {
            setOllamaModels(llm.available_models);
          }
        }
      } catch {
        // ignore if Ollama host is offline
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!config?.values) return;
    setBulletsPerExperience(config.values.default_bullets_per_role ?? 5);
    setPageBudget(config.values.page_budget ?? 1.5);
    setAvoidedWords(config.values.avoided_ai_words ?? [...DEFAULT_AVOIDED_AI_WORDS]);
    setCustomInstructions(config.values.custom_tailor_instructions ?? "");
  }, [config]);

  useEffect(() => {
    try {
      window.localStorage.setItem("careerflow.jobsViewLayout", jobsViewLayout);
      window.localStorage.setItem("careerflow.splitLeftPct", String(splitLeftPct));
      window.localStorage.setItem("careerflow.splitListHeightPx", String(splitListHeightPx));
      window.localStorage.setItem("careerflow.gridCols", String(gridCols));
      window.localStorage.setItem("careerflow.gridRows", String(gridRows));
    } catch {
      // ignore storage quota errors
    }
  }, [jobsViewLayout, splitLeftPct, splitListHeightPx, gridCols, gridRows]);

  const trackName = (id: string) =>
    roleTracks.find((t) => t.id === id)?.display_name || id;

  useEffect(() => {
    setSelectedCities([]);
    setCompanyFilter("all");
    setPostedWithinFilter("all");
    setRoleFilter("all");
    setSourceFilter("all");
    setWorkTypeFilter("all");
    setStatusFilter("all");
    setMinMatchFilter(0);
    setOnlyH1bConfirmed(false);
    setOnlyWithSalary(false);
    setSortBy("latest");
    setJobQuery("");
    setAuditReasonFilter("all");
    setAuditLocationFilter("all");
    setAuditSourceFilter("all");
    setAuditSortBy("latest_posted");
    setDiscardedSortBy("latest");
    setAuditQuery("");
    setSelectedFilteredIds([]);
    setSelectedDiscardedIds([]);
  }, [session.id]);

  useEffect(() => {
    setAuditReasonFilter("all");
    setAuditLocationFilter("all");
    setAuditSourceFilter("all");
    setAuditQuery("");
    setSelectedFilteredIds([]);
    setSelectedDiscardedIds([]);
  }, [workspaceView]);

  const autoFilteredItems = useMemo(
    () => filteredItems.filter((item) => item.category === "auto_filtered"),
    [filteredItems]
  );

  const seenSkippedItems = useMemo(
    () => filteredItems.filter((item) => item.category === "seen_skipped"),
    [filteredItems]
  );

  const auditOriginByJobId = useMemo(() => {
    const map = new Map<number, SessionFilteredJobResponse>();
    for (const item of filteredItems) {
      if (item.promoted_job_id != null) {
        map.set(item.promoted_job_id, item);
      }
    }
    return map;
  }, [filteredItems]);

  const activeAuditBase = workspaceView === "seen" ? seenSkippedItems : autoFilteredItems;

  const auditReasonCounts = useMemo(() => {
    const counts = new Map<string, { reason: string; label: string; count: number }>();
    for (const item of activeAuditBase) {
      const codes = item.filter_reasons?.length ? item.filter_reasons : [item.filter_reason];
      const labels = item.reason_labels?.length ? item.reason_labels : [item.reason_label];
      const seenInItem = new Set<string>();
      codes.forEach((code, idx) => {
        if (!code || seenInItem.has(code)) return;
        seenInItem.add(code);
        const label = labels[idx] || item.reason_label || code;
        const prev = counts.get(code);
        if (prev) {
          prev.count += 1;
        } else {
          counts.set(code, { reason: code, label, count: 1 });
        }
      });
    }
    return Array.from(counts.values()).sort((a, b) => b.count - a.count);
  }, [activeAuditBase]);

  const auditLocations = useMemo(() => {
    const set = new Set<string>();
    for (const item of activeAuditBase) {
      set.add((item.location || "Unspecified").trim() || "Unspecified");
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [activeAuditBase]);

  const auditSources = useMemo(() => {
    const set = new Set<string>();
    for (const item of activeAuditBase) {
      if (item.source) set.add(item.source);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [activeAuditBase]);

  const visibleAuditItems = useMemo(() => {
    const q = auditQuery.trim().toLowerCase();
    const filtered = activeAuditBase.filter((item) => {
      if (auditReasonFilter !== "all") {
        const codes = item.filter_reasons?.length ? item.filter_reasons : [item.filter_reason];
        if (!codes.includes(auditReasonFilter)) return false;
      }
      if (auditLocationFilter !== "all") {
        const loc = (item.location || "Unspecified").trim() || "Unspecified";
        if (loc !== auditLocationFilter) return false;
      }
      if (auditSourceFilter !== "all" && item.source !== auditSourceFilter) {
        return false;
      }
      if (q) {
        const labelsStr = (item.reason_labels ?? [item.reason_label]).join(" ");
        const notesStr = (item.suitability_notes ?? []).join(" ");
        const hay =
          `${item.company} ${item.title} ${item.location} ${item.source} ${labelsStr} ${notesStr}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    return [...filtered].sort((a, b) => {
      if (auditSortBy === "most_reasons") {
        const rcDiff =
          (b.filter_reasons?.length || 1) - (a.filter_reasons?.length || 1);
        if (rcDiff !== 0) return rcDiff;
      } else if (auditSortBy === "logged_recent") {
        return b.id - a.id;
      } else if (auditSortBy === "company_az") {
        return a.company.localeCompare(b.company) || a.title.localeCompare(b.title);
      } else if (auditSortBy === "title_az") {
        return a.title.localeCompare(b.title) || a.company.localeCompare(b.company);
      }
      const timeDiff =
        parsePostingMs(b.posted_at, b.created_at) -
        parsePostingMs(a.posted_at, a.created_at);
      return timeDiff !== 0 ? timeDiff : b.id - a.id;
    });
  }, [
    activeAuditBase,
    auditReasonFilter,
    auditLocationFilter,
    auditSourceFilter,
    auditSortBy,
    auditQuery,
  ]);

  const visibleDiscardedJobs = useMemo(() => {
    const q = auditQuery.trim().toLowerCase();
    const filtered = discardedJobs.filter((j) => {
      if (!q) return true;
      const hay =
        `${j.analysis.company} ${j.analysis.title} ${j.analysis.location} ${j.source}`.toLowerCase();
      return hay.includes(q);
    });
    return [...filtered].sort((a, b) => {
      if (discardedSortBy === "company_az") {
        return (
          a.analysis.company.localeCompare(b.analysis.company) ||
          a.analysis.title.localeCompare(b.analysis.title)
        );
      }
      if (discardedSortBy === "title_az") {
        return (
          a.analysis.title.localeCompare(b.analysis.title) ||
          a.analysis.company.localeCompare(b.analysis.company)
        );
      }
      const timeDiff =
        parsePostingMs(b.posted_at, b.created_at) -
        parsePostingMs(a.posted_at, a.created_at);
      return timeDiff !== 0 ? timeDiff : b.id - a.id;
    });
  }, [discardedJobs, auditQuery, discardedSortBy]);

  const availableSources = useMemo(() => {
    const set = new Set<string>();
    for (const j of jobs) {
      if (j.source) set.add(j.source);
    }
    return Array.from(set).sort((a, b) => a.localeCompare(b));
  }, [jobs]);

  const similarityAnchorJob = useMemo(() => {
    if (selectedJobId != null) {
      const direct = jobs.find((j) => j.id === selectedJobId);
      if (direct) return direct;
    }
    if (jobs.length === 0) return null;
    return [...jobs].sort((a, b) => {
      const diff =
        parsePostingMs(b.posted_at, b.created_at) -
        parsePostingMs(a.posted_at, a.created_at);
      return diff !== 0 ? diff : b.id - a.id;
    })[0];
  }, [jobs, selectedJobId]);

  const companyOpenRoles = useMemo(() => {
    const counts = new Map<string, number>();
    for (const j of jobs) {
      const comp = (j.analysis.company || "Unknown").trim() || "Unknown";
      counts.set(comp, (counts.get(comp) ?? 0) + 1);
    }
    const sorted = [...counts.entries()]
      .map(([company, count]) => ({ company, count }))
      .sort((a, b) => b.count - a.count || a.company.localeCompare(b.company));
    return { counts, sorted };
  }, [jobs]);

  const hasActiveSavedFilters =
    selectedCities.length > 0 ||
    companyFilter !== "all" ||
    postedWithinFilter !== "all" ||
    roleFilter !== "all" ||
    sourceFilter !== "all" ||
    workTypeFilter !== "all" ||
    statusFilter !== "all" ||
    minMatchFilter > 0 ||
    onlyH1bConfirmed ||
    onlyWithSalary ||
    jobQuery.trim() !== "";

  const resetSavedFilters = () => {
    setSelectedCities([]);
    setCompanyFilter("all");
    setPostedWithinFilter("all");
    setRoleFilter("all");
    setSourceFilter("all");
    setWorkTypeFilter("all");
    setStatusFilter("all");
    setMinMatchFilter(0);
    setOnlyH1bConfirmed(false);
    setOnlyWithSalary(false);
    setJobQuery("");
  };

  const filteredJobs = useMemo(() => {
    const q = jobQuery.trim().toLowerCase();
    const nowMs = Date.now();
    const windowMsMap: Record<string, number> = {
      "1h": 3600_000,
      "6h": 6 * 3600_000,
      "24h": 24 * 3600_000,
      "3d": 3 * 86400_000,
      "7d": 7 * 86400_000,
    };
    const maxAgeMs = postedWithinFilter !== "all" ? windowMsMap[postedWithinFilter] : undefined;

    const matching = jobs.filter((j) => {
      if (
        selectedCities.length > 0 &&
        !selectedCities.includes(j.analysis.location || "Unspecified")
      ) {
        return false;
      }
      if (
        companyFilter !== "all" &&
        ((j.analysis.company || "Unknown").trim() || "Unknown") !== companyFilter
      ) {
        return false;
      }
      if (maxAgeMs != null) {
        const postedMs = parsePostingMs(j.posted_at, j.created_at);
        if (!postedMs || nowMs - postedMs > maxAgeMs) {
          return false;
        }
      }
      if (roleFilter !== "all" && j.analysis.role_track !== roleFilter) {
        return false;
      }
      if (sourceFilter !== "all" && j.source !== sourceFilter) {
        return false;
      }
      if (workTypeFilter !== "all" && j.work_type !== workTypeFilter) {
        return false;
      }
      if (statusFilter === "unapplied_only") {
        if (["applied", "screening", "interviewing", "offer"].includes(j.application_status)) {
          return false;
        }
      } else if (statusFilter === "in_progress") {
        if (!["applied", "screening", "interviewing", "offer", "resume_created"].includes(j.application_status)) {
          return false;
        }
      } else if (statusFilter === "applied_pile") {
        if (!["applied", "screening", "interviewing", "offer"].includes(j.application_status)) {
          return false;
        }
      } else if (statusFilter !== "all" && j.application_status !== statusFilter) {
        return false;
      }
      if (minMatchFilter > 0 && j.relevance_score < minMatchFilter) {
        return false;
      }
      if (onlyH1bConfirmed && j.work_auth !== "h1b_ok") {
        return false;
      }
      if (onlyWithSalary && j.analysis.salary.min_amount == null) {
        return false;
      }
      if (q) {
        const skillsText = (j.analysis.weighted_skills ?? [])
          .map((s) => s.keyword)
          .join(" ");
        const hay =
          `${j.analysis.company} ${j.analysis.title} ${j.analysis.location} ${j.source} ${skillsText}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    return [...matching].sort((a, b) => {
      if (sortBy === "similar_selected" && similarityAnchorJob) {
        if (a.id === similarityAnchorJob.id && b.id !== similarityAnchorJob.id) return -1;
        if (b.id === similarityAnchorJob.id && a.id !== similarityAnchorJob.id) return 1;
        const simDiff =
          computeSimilarityPercent(b, similarityAnchorJob) -
          computeSimilarityPercent(a, similarityAnchorJob);
        if (simDiff !== 0) return simDiff;
        return b.relevance_score - a.relevance_score;
      }
      if (sortBy === "company_open_roles") {
        const compA = (a.analysis.company || "Unknown").trim() || "Unknown";
        const compB = (b.analysis.company || "Unknown").trim() || "Unknown";
        const countDiff =
          (companyOpenRoles.counts.get(compB) ?? 0) -
          (companyOpenRoles.counts.get(compA) ?? 0);
        if (countDiff !== 0) return countDiff;
        const compCmp = compA.localeCompare(compB);
        if (compCmp !== 0) return compCmp;
        return b.relevance_score - a.relevance_score;
      }
      if (sortBy === "match_score") {
        const scoreDiff = b.relevance_score - a.relevance_score;
        if (scoreDiff !== 0) return scoreDiff;
      } else if (sortBy === "salary_high") {
        const compDiff = effectiveAnnualComp(b) - effectiveAnnualComp(a);
        if (compDiff !== 0) return compDiff;
      } else if (sortBy === "oldest") {
        const timeDiff =
          parsePostingMs(a.posted_at, a.created_at) -
          parsePostingMs(b.posted_at, b.created_at);
        return timeDiff !== 0 ? timeDiff : a.id - b.id;
      } else if (sortBy === "company_az") {
        return (
          a.analysis.company.localeCompare(b.analysis.company) ||
          a.analysis.title.localeCompare(b.analysis.title)
        );
      } else if (sortBy === "title_az") {
        return (
          a.analysis.title.localeCompare(b.analysis.title) ||
          a.analysis.company.localeCompare(b.analysis.company)
        );
      }
      const timeDiff =
        parsePostingMs(b.posted_at, b.created_at) -
        parsePostingMs(a.posted_at, a.created_at);
      return timeDiff !== 0 ? timeDiff : b.id - a.id;
    });
  }, [
    jobs,
    selectedCities,
    companyFilter,
    postedWithinFilter,
    companyOpenRoles,
    roleFilter,
    sourceFilter,
    workTypeFilter,
    statusFilter,
    minMatchFilter,
    onlyH1bConfirmed,
    onlyWithSalary,
    jobQuery,
    sortBy,
    similarityAnchorJob,
  ]);

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {
      ready: 0,
      applied: 0,
      screening: 0,
      interviewing: 0,
      offer: 0,
      rejected: 0,
      resume_created: 0,
    };
    for (const j of jobs) {
      const st = j.application_status || "ready";
      counts[st] = (counts[st] || 0) + 1;
    }
    return counts;
  }, [jobs]);

  const inProgressTotal =
    (statusCounts.applied || 0) +
    (statusCounts.screening || 0) +
    (statusCounts.interviewing || 0) +
    (statusCounts.offer || 0) +
    (statusCounts.resume_created || 0);

  const selectedJob = useMemo(
    () => filteredJobs.find((j) => j.id === selectedJobId) || filteredJobs[0] || null,
    [filteredJobs, selectedJobId]
  );

  const selectedJobSuitabilityReasons = useMemo(() => {
    if (!selectedJob) return [];
    const originAudit = auditOriginByJobId.get(selectedJob.id) ?? null;
    return evaluateJobSuitability(selectedJob, scoreReport, config, originAudit, trackName);
  }, [selectedJob, scoreReport, config, auditOriginByJobId, roleTracks]);

  const allPostingSkills = useMemo(() => {
    if (!selectedJob) return [];
    return extractAllPostingSkills(
      selectedJob.raw_text,
      selectedJob.analysis.weighted_skills,
      roleTracks
    );
  }, [selectedJob, roleTracks]);

  const parsedJdBlocks = useMemo(() => {
    if (!selectedJob) return [];
    return parseJdIntoBlocks(selectedJob.raw_text);
  }, [selectedJob]);

  const matchedKeywordSet = useMemo(() => {
    return new Set((scoreReport?.matched_skills ?? []).map((s) => s.keyword.toLowerCase()));
  }, [scoreReport]);

  const missingKeywordSet = useMemo(() => {
    return new Set((scoreReport?.missing_skills ?? []).map((s) => s.keyword.toLowerCase()));
  }, [scoreReport]);

  const resumes = resumeState?.resumes ?? [];

  const toggleCard = (key: string) =>
    setCollapsedCards((prev) => ({ ...prev, [key]: !prev[key] }));

  const updateJobProgress = (jobId: number, patch: Partial<JobProgressState>) => {
    setJobProgressMap((prev) => {
      const next = {
        ...prev,
        [jobId]: {
          ...prev[jobId],
          ...patch,
          updatedAt: new Date().toISOString(),
        },
      };
      saveJobProgressMap(next);
      return next;
    });
  };

  const pendingDownloadJobs = useMemo(
    () =>
      jobs.filter((j) => {
        if (selectedJob && j.id === selectedJob.id) return false;
        const st = computeJobStage(j, jobProgressMap[j.id]);
        return st.isPendingDownload;
      }),
    [jobs, jobProgressMap, selectedJob?.id]
  );

  // Sync previous job draft before switching, mark new job visited, and restore or initialize draft
  useEffect(() => {
    const prevId = prevSelectedJobIdRef.current;
    if (
      prevId != null &&
      prevId !== selectedJob?.id &&
      tailorPreview &&
      editedResume
    ) {
      const snap: JobDraftSnapshot = {
        resumeId: selectedResumeId,
        scoreReport,
        tailorPreview,
        editedResume,
        exportResult,
        editHistory: editHistoryByJob[prevId],
        bulletsPerProject,
      };
      jobDraftsRef.current[prevId] = snap;
      saveJobDraft(prevId, snap);
    }
    prevSelectedJobIdRef.current = selectedJob?.id ?? null;

    if (!selectedJob) {
      setScoreReport(null);
      setLiveReport(null);
      setTailorPreview(null);
      setEditedResume(null);
      setExportResult(null);
      return;
    }

    updateJobProgress(selectedJob.id, { visited: true });

    const preferredByRole = resumes.find(
      (r) => r.is_base && r.role_track === selectedJob.analysis.role_track
    );
    const anyBase = resumes.find((r) => r.is_base);
    const defaultResId = preferredByRole?.id ?? anyBase?.id ?? resumes[0]?.id ?? null;

    const cachedDraft = jobDraftsRef.current[selectedJob.id] || loadJobDraft(selectedJob.id);
    if (
      cachedDraft &&
      (cachedDraft.resumeId === defaultResId || cachedDraft.resumeId != null)
    ) {
      jobDraftsRef.current[selectedJob.id] = cachedDraft;
      skipNextAutoScoreRef.current = true;
      setSelectedResumeId(cachedDraft.resumeId);
      setScoreReport(cachedDraft.scoreReport);
      setTailorPreview(cachedDraft.tailorPreview);
      setLiveReport(cachedDraft.tailorPreview.tailored_report);
      setEditedResume(cachedDraft.editedResume);
      setExportResult(cachedDraft.exportResult);
      if (cachedDraft.tailorStrategy) {
        setTailorStrategy(cachedDraft.tailorStrategy);
      }
      if (cachedDraft.pageBudget) {
        setPageBudget(cachedDraft.pageBudget);
      }
      if (cachedDraft.targetSections) {
        setTargetSections(cachedDraft.targetSections);
      }
      if (cachedDraft.autoSize !== undefined) {
        setAutoSize(cachedDraft.autoSize);
      }
      if (cachedDraft.customRoleBulletCounts) {
        setCustomRoleBulletCounts(cachedDraft.customRoleBulletCounts);
      }
      if (cachedDraft.bulletsPerProject !== undefined) {
        setBulletsPerProject(cachedDraft.bulletsPerProject);
      }
      if (cachedDraft.editHistory) {
        setEditHistoryByJob((prev) => ({ ...prev, [selectedJob.id]: cachedDraft.editHistory! }));
      }
      return;
    }

    setSelectedResumeId(defaultResId);
    setExportResult(null);
    setTailorPreview(null);
    setEditedResume(null);
    setLiveReport(null);
    setSectionNotice(null);

    if (defaultResId != null) {
      let cancelled = false;
      void (async () => {
        try {
          const [rep, prev] = await Promise.all([
            api.scoreJob(selectedJob.id, defaultResId),
            api.previewTailor(selectedJob.id, defaultResId, adaptLocation, false, true, {
              tailorStrategy: "fallback_script",
              bulletsPerExperience: autoSize ? null : bulletsPerExperience,
              bulletsPerRoleCounts: autoSize ? undefined : customRoleBulletCounts,
              autoSize,
              pageBudget,
              avoidedWords,
              customInstructions,
              targetScoreMin: 80,
              targetScoreMax: 85,
            }),
          ]);
          if (cancelled) return;
          skipNextAutoScoreRef.current = true;
          setScoreReport(rep);
          setTailorPreview(prev);
          setLiveReport(prev.tailored_report);
          setEditedResume(JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume);
        } catch {
          if (!cancelled) {
            setScoreReport(null);
            setLiveReport(null);
          }
        }
      })();
      return () => {
        cancelled = true;
      };
    } else {
      setScoreReport(null);
      setLiveReport(null);
    }
  }, [selectedJob?.id, resumes.length]);

  // Keep draft ref synced on every local edit + debounced auto-rescore
  useEffect(() => {
    if (!selectedJob || !editedResume || !tailorPreview) return;
    const currentSnap: JobDraftSnapshot = {
      resumeId: selectedResumeId,
      scoreReport,
      tailorPreview,
      editedResume,
      exportResult,
      editHistory: editHistoryByJob[selectedJob.id],
      tailorStrategy,
      pageBudget,
      targetSections,
      autoSize,
      customRoleBulletCounts,
    };
    jobDraftsRef.current[selectedJob.id] = currentSnap;
    saveJobDraft(selectedJob.id, currentSnap);

    if (skipNextAutoScoreRef.current) {
      skipNextAutoScoreRef.current = false;
      return;
    }

    const timer = window.setTimeout(() => {
      void (async () => {
        try {
          const rep = await api.scoreDraftResume(
            selectedJob.id,
            editedResume,
            selectedResumeId ?? undefined
          );
          setLiveReport(rep);
        } catch {
          // ignore transient scoring failures while typing
        }
      })();
    }, 650);
    return () => window.clearTimeout(timer);
  }, [editedResume, selectedJob?.id]);

  const handleDiscardJob = async (jobId: number) => {
    setError(null);
    try {
      await api.patchJob(jobId, { disposition: "discarded" });
      await onJobsUpdated();
      setNotice("Job discarded permanently and won't be pulled again.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to discard job.");
    }
  };

  const handleStatusChange = async (jobId: number, status: ApplicationStatus) => {
    setError(null);
    try {
      await api.patchJob(jobId, { application_status: status });
      await onJobsUpdated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status.");
    }
  };

  const handleResumeSwitch = async (resumeId: number) => {
    if (!selectedJob) return;
    setSelectedResumeId(resumeId);
    setExportResult(null);
    setActionBusy(true);
    setError(null);
    try {
      const [rep, prev] = await Promise.all([
        api.scoreJob(selectedJob.id, resumeId),
        api.previewTailor(selectedJob.id, resumeId, adaptLocation, false, true, {
          tailorStrategy: "fallback_script",
          bulletsPerExperience: autoSize ? null : bulletsPerExperience,
          bulletsPerRoleCounts: autoSize ? undefined : customRoleBulletCounts,
          autoSize,
          pageBudget,
          avoidedWords,
          customInstructions,
          targetScoreMin: 80,
          targetScoreMax: 85,
        }),
      ]);
      skipNextAutoScoreRef.current = true;
      setScoreReport(rep);
      setTailorPreview(prev);
      setLiveReport(prev.tailored_report);
      setEditedResume(JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to evaluate resume.");
    } finally {
      setActionBusy(false);
    }
  };

  const handleToggleAdaptLocation = async (nextVal: boolean) => {
    setAdaptLocation(nextVal);
    if (!selectedJob || selectedResumeId == null) return;
    setActionBusy(true);
    try {
      const prev = await api.previewTailor(selectedJob.id, selectedResumeId, nextVal, false, true, {
        tailorStrategy: "fallback_script",
        bulletsPerExperience: autoSize ? null : bulletsPerExperience,
        bulletsPerRoleCounts: autoSize ? undefined : customRoleBulletCounts,
        autoSize,
        pageBudget,
        avoidedWords,
        customInstructions,
        targetScoreMin: 80,
        targetScoreMax: 85,
      });
      skipNextAutoScoreRef.current = true;
      setTailorPreview(prev);
      setLiveReport(prev.tailored_report);
      setEditedResume(JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh preview.");
    } finally {
      setActionBusy(false);
    }
  };

  const appendJobEditHistory = (
    jobId: number,
    entry: Omit<EditHistoryEntry, "step" | "timestamp">
  ) => {
    setEditHistoryByJob((prev) => {
      const existing = prev[jobId] ?? [];
      const baseStepOffset = 2; // #1 is Initial Base Resume ATS Score
      const snapshot =
        entry.resumeSnapshot ??
        (editedResume ? (JSON.parse(JSON.stringify(editedResume)) as CanonicalResume) : undefined);
      return {
        ...prev,
        [jobId]: [
          ...existing,
          {
            ...entry,
            resumeSnapshot: snapshot,
            step: existing.length + baseStepOffset,
            timestamp: new Date().toISOString(),
          },
        ],
      };
    });
  };

  const recordManualEdit = (sectionLabel: string, detail: string) => {
    if (!selectedJob) return;
    const key = `${selectedJob.id}:${sectionLabel}`;
    const now = Date.now();
    const prevTs = lastManualEditRef.current[key] ?? 0;
    lastManualEditRef.current[key] = now;
    const currentScore =
      liveReport?.overall_score ?? tailorPreview?.tailored_score ?? 0;
    const actionLabel = `Manual Edit (${sectionLabel})`;

    setEditHistoryByJob((prev) => {
      const list = prev[selectedJob.id] ?? [];
      const currentSnap = editedResume ? (JSON.parse(JSON.stringify(editedResume)) as CanonicalResume) : undefined;
      if (now - prevTs < 8000 && list.length > 0) {
        const last = list[list.length - 1];
        if (last.action === actionLabel) {
          const updated = [...list];
          updated[updated.length - 1] = {
            ...last,
            detail,
            atsScore: currentScore,
            timestamp: new Date().toISOString(),
            resumeSnapshot: currentSnap ?? last.resumeSnapshot,
          };
          return { ...prev, [selectedJob.id]: updated };
        }
      }
      return {
        ...prev,
        [selectedJob.id]: [
          ...list,
          {
            step: list.length + 2,
            timestamp: new Date().toISOString(),
            action: actionLabel,
            detail,
            atsScore: currentScore,
            engineLabel: "Manual Editor",
            resumeSnapshot: currentSnap,
          },
        ],
      };
    });
  };

  const handleRevertToStep = (entry: EditHistoryEntry) => {
    if (!selectedJob || !entry.resumeSnapshot) return;
    const restored = JSON.parse(JSON.stringify(entry.resumeSnapshot)) as CanonicalResume;
    setEditedResume(restored);
    setNotice(`Previewing version from Step #${entry.step}: ${entry.action} (${entry.atsScore}% ATS score).`);
    if (tailorPreview) {
      setTailorPreview({
        ...tailorPreview,
        tailored_resume: restored,
        tailored_score: entry.atsScore,
      });
    }
  };

  const handleAddStudioAvoidedWord = () => {
    const word = customAvoidedStudioWord.trim().toLowerCase();
    if (!word) return;
    if (!avoidedWords.includes(word)) {
      setAvoidedWords((prev) => [...prev, word]);
      setNotice(`Added "${word}" to blocked AI words.`);
    }
    setCustomAvoidedStudioWord("");
  };

  const handleRunUnifiedTailor = async (strategyOverride?: TailorStrategy) => {
    if (!selectedJob || selectedResumeId == null) return;
    const effectiveStrategy = strategyOverride ?? tailorStrategy;
    const useLlm = effectiveStrategy !== "fallback_script";
    setLlmTailorBusy(true);
    setTailorStepIndex(1);
    const stepTimer = window.setInterval(() => {
      setTailorStepIndex((prev) => (prev < 4 ? prev + 1 : prev));
    }, 2500);
    setError(null);
    setNotice(null);
    try {
      const prev = await api.previewTailor(
        selectedJob.id,
        selectedResumeId,
        adaptLocation,
        useLlm,
        true,
        {
          tailorStrategy: effectiveStrategy,
          bulletsPerExperience: autoSize ? null : bulletsPerExperience,
          bulletsPerRoleCounts: autoSize ? undefined : customRoleBulletCounts,
          bulletsPerProject: bulletsPerProject === "" ? null : Number(bulletsPerProject),
          autoSize,
          pageBudget,
          avoidedWords,
          customInstructions,
          targetScoreMin: 80,
          targetScoreMax: 85,
          llmModel: selectedStudioModel || undefined,
          targetSections,
        }
      );
      window.clearInterval(stepTimer);
      setTailorStepIndex(5);
      skipNextAutoScoreRef.current = true;
      const cloned = JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume;
      setTailorPreview(prev);
      setLiveReport(prev.tailored_report);
      setEditedResume(cloned);
      setExportResult(null);
      if (prev.page_budget) {
        setPageBudget(prev.page_budget);
      }
      const snap: JobDraftSnapshot = {
        resumeId: selectedResumeId,
        scoreReport,
        tailorPreview: prev,
        editedResume: cloned,
        exportResult: null,
        editHistory: editHistoryByJob[selectedJob.id],
        tailorStrategy,
        pageBudget: prev.page_budget ?? pageBudget,
        targetSections,
        autoSize,
        customRoleBulletCounts,
        bulletsPerProject,
      };
      jobDraftsRef.current[selectedJob.id] = snap;
      saveJobDraft(selectedJob.id, snap);
      updateJobProgress(selectedJob.id, {
        visited: true,
        tailored: true,
        downloaded: false,
        lastScore: prev.tailored_score,
      });
      const modeLabel =
        prev.tailor_mode === "ollama_llm"
          ? `Local Ollama (${prev.model_used || "AI"})`
          : "Fallback Reasoning Script";
      const bandLabel = prev.in_target_band
        ? "Inside 80–85% target band"
        : `Calibrated to ${prev.tailored_score}%`;
      setNotice(
        `Tailored, humanized & sanity-verified via ${modeLabel}. Score: ${prev.base_score}% -> ${prev.tailored_score}% (${bandLabel}). ${
          prev.sanity_summary || ""
        }`.trim()
      );
      appendJobEditHistory(selectedJob.id, {
        action: "Tailored Full Resume",
        detail: `Tailored, humanized & sanity-checked (${bandLabel})`,
        atsScore: prev.tailored_score,
        engineLabel: modeLabel,
        resumeSnapshot: cloned,
      });
    } catch (err) {
      window.clearInterval(stepTimer);
      setLlmTailorBusy(false);
      setTailorStepIndex(1);
      setError(err instanceof Error ? err.message : "Resume tailoring failed.");
    } finally {
      window.clearInterval(stepTimer);
      window.setTimeout(() => {
        setLlmTailorBusy(false);
        setTailorStepIndex(1);
      }, 1800);
    }
  };

  const handleTailorSection = async (section: ResumeSectionName) => {
    if (!selectedJob || !editedResume) return;
    const engine = sectionEngines[section];
    const promptText = sectionPrompts[section].trim();

    setSectionBusy(section);
    setError(null);
    setSectionNotice(null);
    try {
      const res = await api.tailorSection({
        job_id: selectedJob.id,
        resume_id: selectedResumeId,
        section,
        current_resume: editedResume,
        prompt: promptText,
        engine,
        model: engine === "ollama" && sectionModelOverride ? sectionModelOverride : null,
        avoided_words: avoidedWords,
        bullets_per_experience: autoSize ? null : bulletsPerExperience,
        page_budget: pageBudget,
      });
      skipNextAutoScoreRef.current = true;
      const updated = JSON.parse(JSON.stringify(res.updated_resume)) as CanonicalResume;
      setEditedResume(updated);
      setExportResult(null);
      if (res.tailored_report) {
        setLiveReport(res.tailored_report);
      }
      if (tailorPreview) {
        const nextPreview: TailorPreviewResponse = {
          ...tailorPreview,
          tailored_resume: updated,
          tailored_report: res.tailored_report ?? tailorPreview.tailored_report,
          tailored_score: res.tailored_score ?? tailorPreview.tailored_score,
        };
        setTailorPreview(nextPreview);
        const snap: JobDraftSnapshot = {
          resumeId: selectedResumeId,
          scoreReport,
          tailorPreview: nextPreview,
          editedResume: updated,
          exportResult: null,
          editHistory: editHistoryByJob[selectedJob.id],
        };
        jobDraftsRef.current[selectedJob.id] = snap;
        saveJobDraft(selectedJob.id, snap);
      }
      updateJobProgress(selectedJob.id, {
        visited: true,
        tailored: true,
        downloaded: false,
        lastScore: res.tailored_score ?? undefined,
      });
      const sectionLabel =
        section === "skills"
          ? "Technical Skills"
          : section.charAt(0).toUpperCase() + section.slice(1);
      const engLabel =
        res.engine_used === "ollama_llm"
          ? res.model_used || "Local Ollama"
          : "Fallback Script";
      setSectionNotice(
        res.notice ?? `${sectionLabel} updated via ${engLabel} (ATS: ${res.tailored_score}%).`
      );
      appendJobEditHistory(selectedJob.id, {
        action: `${sectionLabel} Prompt`,
        detail: promptText
          ? `"${promptText.slice(0, 72)}${promptText.length > 72 ? "…" : ""}"`
          : `Re-tailored ${sectionLabel} to match JD`,
        atsScore: res.tailored_score,
        engineLabel: engLabel,
        resumeSnapshot: updated,
      });
    } catch (err) {
      setError(
        err instanceof Error ? err.message : `Failed to update ${section} section.`
      );
    } finally {
      setSectionBusy(null);
    }
  };

  const handleQuickBootstrapResume = async (useOllama: boolean) => {
    if (!selectedJob) return;
    setBootModeBusy(useOllama ? "ollama" : "fallback");
    setError(null);
    setNotice(null);
    try {
      const focusList = bootFocusSkills
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const targetTrack = bootRoleTrack || selectedJob.analysis.role_track || "senior_swe";
      const targetLoc = bootLocation.trim() || selectedJob.analysis.location || "New York, NY";
      const validEmployers = bootEmployers
        .filter((emp) => emp.company.trim().length > 0)
        .map((emp) => ({
          company: emp.company.trim(),
          title: emp.title?.trim() || null,
          location: emp.location?.trim() || null,
          start_date: emp.start_date?.trim() || null,
          end_date: emp.end_date?.trim() || null,
          bullets_count: emp.bullets_count || bulletsPerExperience || 5,
        }));
      const roleBulletCounts = validEmployers.map(
        (emp) => emp.bullets_count || bulletsPerExperience || 5
      );
      const res = await api.bootstrapResume({
        full_name: bootName.trim() || "Alex Rivera",
        location: targetLoc,
        role_track: targetTrack,
        years_experience: Math.max(1, Math.min(20, Number(bootYears) || 5)),
        focus_skills: focusList,
        employers: validEmployers.length > 0 ? validEmployers : undefined,
        recent_company: validEmployers[0]?.company || null,
        prior_company: validEmployers[1]?.company || null,
        graduate_degree: bootGradDegree.trim() || null,
        undergrad_degree: bootUndergradDegree.trim() || null,
        bullets_per_experience: bulletsPerExperience ?? 5,
        bullets_per_role_counts: roleBulletCounts.length > 0 ? roleBulletCounts : null,
        projects_count: Math.max(2, bootProjectsCount),
        page_budget: pageBudget,
        job_id: selectedJob.id,
        use_llm: useOllama,
        save_as_base: true,
      });
      if (onResumesChanged) {
        await onResumesChanged();
      }
      setShowQuickBootstrap(false);
      setSelectedResumeId(res.resume.id);
      const [rep, prev] = await Promise.all([
        api.scoreJob(selectedJob.id, res.resume.id),
        api.previewTailor(selectedJob.id, res.resume.id, adaptLocation, false, true, {
          tailorStrategy: "fallback_script",
          bulletsPerExperience: autoSize ? null : bulletsPerExperience,
          bulletsPerRoleCounts: autoSize ? undefined : customRoleBulletCounts,
          autoSize,
          pageBudget,
          avoidedWords,
          customInstructions,
          targetScoreMin: 80,
          targetScoreMax: 85,
        }),
      ]);
      skipNextAutoScoreRef.current = true;
      setScoreReport(rep);
      setTailorPreview(prev);
      setLiveReport(prev.tailored_report);
      setEditedResume(JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume);
      setNotice(
        `Generated ${res.resume.name} via ${
          res.model_used || "Structured Reasoning Script"
        }. Tailored Match: ${prev.tailored_score}%.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to auto-generate generic resume.");
    } finally {
      setBootModeBusy(null);
    }
  };

  const updateTailoredSummary = (newSummary: string) => {
    if (!editedResume) return;
    setEditedResume({ ...editedResume, summary: newSummary });
    setExportResult(null);
    recordManualEdit("Summary", "Edited summary copy");
  };

  const updateTailoredBullet = (expIdx: number, bulletIdx: number, newText: string) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (next.experience[expIdx]?.bullets[bulletIdx]) {
      next.experience[expIdx].bullets[bulletIdx].text = newText;
      setEditedResume(next);
      setExportResult(null);
      recordManualEdit(
        "Experience",
        `Edited bullet #${bulletIdx + 1} (${next.experience[expIdx].company})`
      );
    }
  };

  const addTailoredBullet = (expIdx: number) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    const exp = next.experience[expIdx];
    if (!exp) return;
    exp.bullets.push({
      id: `${exp.id || `exp_${expIdx}`}_u${Date.now()}`,
      text: "",
      provenance: "SUGGESTED_DRAFT",
      approved: true,
      tags: [],
    });
    setEditedResume(next);
    setExportResult(null);
    recordManualEdit("Experience", `Added bullet under ${exp.company}`);
  };

  const removeTailoredBullet = (expIdx: number, bulletIdx: number) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    const exp = next.experience[expIdx];
    if (!exp || exp.bullets.length <= 1) return;
    exp.bullets.splice(bulletIdx, 1);
    setEditedResume(next);
    setExportResult(null);
    recordManualEdit("Experience", `Removed bullet #${bulletIdx + 1} (${exp.company})`);
  };

  const updateProjectField = (
    projIdx: number,
    patch: { name?: string; link?: string; tech_stack?: string[] }
  ) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (!next.projects[projIdx]) return;
    next.projects[projIdx] = { ...next.projects[projIdx], ...patch };
    setEditedResume(next);
    setExportResult(null);
    recordManualEdit("Projects", `Updated project #${projIdx + 1} metadata`);
  };

  const updateProjectBullet = (projIdx: number, bulletIdx: number, newText: string) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (next.projects[projIdx]?.bullets[bulletIdx]) {
      next.projects[projIdx].bullets[bulletIdx].text = newText;
      setEditedResume(next);
      setExportResult(null);
      recordManualEdit(
        "Projects",
        `Edited project #${projIdx + 1} bullet #${bulletIdx + 1}`
      );
    }
  };

  const addProjectBullet = (projIdx: number) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (next.projects[projIdx]) {
      next.projects[projIdx].bullets.push({
        id: `pb_${Date.now()}_${Math.random().toString(36).substring(2, 6)}`,
        text: "",
        provenance: "SUGGESTED_DRAFT",
        approved: true,
        tags: [],
      });
      setEditedResume(next);
      setExportResult(null);
      recordManualEdit("Projects", `Added bullet to project #${projIdx + 1}`);
    }
  };

  const removeProjectBullet = (projIdx: number, bulletIdx: number) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (next.projects[projIdx]?.bullets) {
      next.projects[projIdx].bullets.splice(bulletIdx, 1);
      setEditedResume(next);
      setExportResult(null);
      recordManualEdit("Projects", `Removed bullet #${bulletIdx + 1} from project #${projIdx + 1}`);
    }
  };

  const addProject = () => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    next.projects.push({
      id: `proj_${Date.now()}`,
      name: `${selectedJob?.analysis.title || "Engineering"} Project`,
      tech_stack: ["Python", "FastAPI", "Docker"],
      link: "",
      bullets: [
        {
          id: `pb_${Date.now()}`,
          text: "",
          provenance: "SUGGESTED_DRAFT",
          approved: true,
          tags: [],
        },
      ],
    });
    setEditedResume(next);
    setExportResult(null);
    recordManualEdit("Projects", "Added new project entry");
  };

  const updateSkillCategory = (catIdx: number, categoryName: string, itemsCsv: string) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (!next.skills[catIdx]) return;
    next.skills[catIdx] = {
      category: categoryName,
      items: itemsCsv
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    };
    setEditedResume(next);
    setExportResult(null);
    recordManualEdit("Technical Skills", `Updated category "${categoryName || `#${catIdx + 1}`}"`);
  };

  const addSkillCategory = () => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    next.skills.push({ category: "Additional Stack", items: [] });
    setEditedResume(next);
    setExportResult(null);
    recordManualEdit("Technical Skills", "Added new skill category");
  };

  const markJobDownloaded = (jobId: number) => {
    updateJobProgress(jobId, { visited: true, tailored: true, downloaded: true });
  };

  const handleCreateResume = async (formats?: ("pdf" | "docx")[]) => {
    if (!selectedJob || selectedResumeId == null) {
      setError("Add or generate a base resume first.");
      return;
    }
    setActionBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.exportResume(
        selectedJob.id,
        selectedResumeId,
        editedResume ?? undefined,
        formats,
        pageBudget
      );
      setExportResult(res);
      setLiveReport(res.report);
      updateJobProgress(selectedJob.id, {
        visited: true,
        tailored: true,
        lastScore: res.ats_score,
      });
      await onJobsUpdated();
      const exportedFiles = res.generated_files.filter(
        (f) => f.endsWith(".pdf") || f.endsWith(".docx")
      );
      appendJobEditHistory(selectedJob.id, {
        action: "Exported Resume",
        detail: `Generated ${exportedFiles.join(", ")} (${pageBudget}p layout)`,
        atsScore: res.ats_score,
        engineLabel: "PDF/DOCX Export",
      });
      setNotice(
        `Created ${exportedFiles.join(", ")} — click Download below to save your unique file.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export resume.");
    } finally {
      setActionBusy(false);
    }
  };

  const handleBulkExportSession = async () => {
    setBulkBusy(true);
    setBulkError(null);
    try {
      const res = await api.bulkExportSession(session.id, {
        resume_id: selectedResumeId ?? null,
        formats: ["pdf", "docx"],
        tailor_strategy: bulkStrategy,
        adapt_location: adaptLocation,
        auto_size: bulkAutoSize,
        target_score_min: 80,
        target_score_max: 85,
        include_already_created: bulkIncludeAlready,
        avoided_words: avoidedWords,
        custom_instructions: customInstructions.trim() || null,
      });
      setBulkResult(res);
      for (const item of res.items) {
        if (!item.error) {
          updateJobProgress(item.job_id, {
            visited: true,
            tailored: true,
            downloaded: true,
            lastScore: item.tailored_score,
          });
          if (item.tailored_resume) {
            const parsedRes = item.tailored_resume as CanonicalResume;
            const draftSnap: JobDraftSnapshot = {
              resumeId: selectedResumeId,
              tailorPreview: {
                job_id: item.job_id,
                resume_id: selectedResumeId ?? 0,
                resume_name: "Selected Resume",
                base_score: item.base_score,
                tailored_score: item.tailored_score,
                base_report: item.tailored_report as ATSReport,
                tailored_report: item.tailored_report as ATSReport,
                field_changes: [],
                experience_comparisons: [],
                tailor_mode: (item.tailor_mode || "fallback_script") as "fallback_script" | "deterministic" | "ollama_llm",
                in_target_band: item.tailored_score >= 80 && item.tailored_score <= 85,
                page_budget: bulkAutoSize ? 2 : pageBudget,
                tailored_resume: parsedRes,
                humanized_count: 0,
                sanity_passed: true,
                reasoning_steps: [],
                added_jd_skills: [],
              },
              editedResume: parsedRes,
              scoreReport: item.tailored_report as ATSReport,
              exportResult: item.export_result ?? null,
              editHistory: [
                {
                  step: 1,
                  timestamp: new Date().toLocaleTimeString(),
                  action: "Batch Tailored",
                  detail: `Batch generated for ${item.company} (${item.role_track})`,
                  atsScore: item.tailored_score,
                  engineLabel: item.tailor_mode || "Auto",
                  resumeSnapshot: parsedRes,
                },
              ],
            };
            jobDraftsRef.current[item.job_id] = draftSnap;
            saveJobDraft(item.job_id, draftSnap);
            setEditHistoryByJob((prev) => ({
              ...prev,
              [item.job_id]: draftSnap.editHistory ?? [],
            }));
            if (selectedJob && selectedJob.id === item.job_id) {
              setEditedResume(parsedRes);
              setTailorPreview(draftSnap.tailorPreview ?? null);
              if (item.tailored_report) setLiveReport(item.tailored_report as ATSReport);
            }
          }
        }
      }
      await onJobsUpdated();
      setNotice(
        `Bulk generated ${res.succeeded_count} of ${res.processed_count} saved job resumes (calibrated to 80–85% ATS match).`
      );
    } catch (err) {
      setBulkError(err instanceof Error ? err.message : "Bulk resume generation failed.");
    } finally {
      setBulkBusy(false);
    }
  };

  const toggleFilteredSelection = (id: number) => {
    setSelectedFilteredIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const toggleDiscardedSelection = (id: number) => {
    setSelectedDiscardedIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  };

  const handlePromoteSelected = async (idsToPromote: number[]) => {
    if (idsToPromote.length === 0) return;
    setPromotingBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.promoteFilteredJobs(
        session.id,
        idsToPromote,
        promoteRoleOverride || undefined
      );
      setSelectedFilteredIds((prev) => prev.filter((id) => !idsToPromote.includes(id)));
      if (res.saved_jobs.length > 0) {
        setSelectedJobId(res.saved_jobs[0].id);
      }
      await onJobsUpdated();
      const parts: string[] = [];
      if (res.added_count > 0) {
        parts.push(`Added ${res.added_count} job(s) to Saved Jobs`);
      }
      if (res.already_saved_count > 0) {
        parts.push(`${res.already_saved_count} already in Saved Jobs`);
      }
      if (res.failed_count > 0) {
        parts.push(`${res.failed_count} could not be parsed`);
      }
      setNotice(parts.join(" · ") || "Promotion complete.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add selected jobs to Saved List.");
    } finally {
      setPromotingBusy(false);
    }
  };

  const handleRestoreDiscarded = async (idsToRestore: number[]) => {
    if (idsToRestore.length === 0) return;
    setPromotingBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.restoreDiscardedJobs(session.id, idsToRestore);
      setSelectedDiscardedIds((prev) => prev.filter((id) => !idsToRestore.includes(id)));
      if (res.saved_jobs.length > 0) {
        setSelectedJobId(res.saved_jobs[0].id);
      }
      await onJobsUpdated();
      setNotice(
        `Restored ${res.added_count} discarded job(s) back to Saved Jobs.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore discarded jobs.");
    } finally {
      setPromotingBusy(false);
    }
  };

  const handleSelectJobCard = (jobId: number) => {
    setSelectedJobId(jobId);
    updateJobProgress(jobId, { visited: true });
    if (jobsViewLayout === "grid") {
      window.setTimeout(() => {
        document
          .getElementById("selected-job-detail-panel")
          ?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      }, 40);
    }
  };

  const renderJobPlacard = (job: JobPostingResponse, mode: "list" | "grid") => {
    const isSelected = selectedJob?.id === job.id;
    const simPct =
      sortBy === "similar_selected"
        ? computeSimilarityPercent(job, similarityAnchorJob)
        : null;
    const quickFlags = evaluateJobSuitability(
      job,
      null,
      config,
      auditOriginByJobId.get(job.id) ?? null,
      trackName
    );
    const stage = computeJobStage(job, jobProgressMap[job.id]);
    return (
      <div
        key={job.id}
        className={`${mode === "grid" ? "job-card-grid" : "job-item"} ${
          isSelected ? "selected" : ""
        }`}
        onClick={() => handleSelectJobCard(job.id)}
      >
        <div className="stack-sm">
          <div className="row-between" style={{ alignItems: "flex-start", gap: 6 }}>
            <h4 className="job-title" style={mode === "grid" ? { fontSize: 13.5 } : undefined}>
              {job.analysis.title}
            </h4>
            <span className="pill pill-blue mono">{Math.round(job.relevance_score)}%</span>
          </div>
          <div className="job-company" style={mode === "grid" ? { fontSize: 12 } : undefined}>
            {job.analysis.company} &middot; {job.analysis.location || "Unspecified"}
          </div>
          <div className="row-wrap">
            <span className="pill">{trackName(job.analysis.role_track)}</span>
            <span
              className={
                job.analysis.salary.min_amount == null ? "pill" : "pill pill-green"
              }
            >
              {formatCompensation(job)}
            </span>
            <span className={stage.pillClass} title={`Progress: ${stage.label}`}>
              {stage.label}
            </span>
            {job.application_notes && job.application_notes.includes("[Carried from Session") && (
              <span className="pill pill-purple" title="Carried forward from an earlier scrape session with existing progress intact">
                Carried Forward
              </span>
            )}
            {simPct !== null && (
              <span className="pill pill-green">
                {job.id === similarityAnchorJob?.id ? "Selected" : `${simPct}% sim`}
              </span>
            )}
            {quickFlags.length > 0 && (
              <span className="pill pill-amber" title={quickFlags.join(" • ")}>
                {quickFlags.length} caution{quickFlags.length > 1 ? "s" : ""}
              </span>
            )}
          </div>
          <div
            className="job-progress-track"
            title={`Pipeline stage (${stage.stepCount}/4): ${stage.label}`}
          >
            {[1, 2, 3, 4].map((step) => (
              <span
                key={step}
                className={`job-progress-seg ${
                  stage.stepCount >= step ? stage.segClass : ""
                }`}
              />
            ))}
          </div>
        </div>
        <div className="row-between" onClick={(e) => e.stopPropagation()}>
          <span className="small-note">
            {formatSourceLabel(job.source)} &middot;{" "}
            {job.work_type !== "unspecified"
              ? formatWorkTypeLabel(job.work_type)
              : formatJobTypeLabel(job.job_type)}
            {job.work_auth === "h1b_ok" ? " · H-1B" : ""} &middot;{" "}
            {formatPostedAtEastern(job.posted_at)}
          </span>
          <button
            type="button"
            className="btn btn-sm btn-danger-ghost"
            onClick={() => void handleDiscardJob(job.id)}
          >
            Discard
          </button>
        </div>
      </div>
    );
  };

  const renderSectionPromptBox = (
    section: ResumeSectionName,
    sectionTitle: string,
    placeholder: string
  ) => {
    const engine = sectionEngines[section];
    const busyHere = sectionBusy === section;
    return (
      <div className="section-prompt-box">
        <div className="row-between" style={{ marginBottom: 6 }}>
          <strong style={{ fontSize: 12.5 }}>
            Custom Prompt Engine &mdash; {sectionTitle}
          </strong>
          <div className="row-wrap" style={{ gap: 6 }}>
            <select
              style={{ width: "auto" }}
              value={engine}
              onChange={(e) =>
                setSectionEngines((prev) => ({
                  ...prev,
                  [section]: e.target.value as "ollama" | "claude",
                }))
              }
              aria-label={`${sectionTitle} prompt engine`}
            >
              <option value="ollama">Local Ollama</option>
              <option value="fallback_script">Reasoning Script</option>
            </select>
            {engine === "ollama" && ollamaModels.length > 0 && (
              <select
                style={{ width: "auto", maxWidth: 190 }}
                value={sectionModelOverride}
                onChange={(e) => setSectionModelOverride(e.target.value)}
                aria-label={`${sectionTitle} Ollama model`}
              >
                <option value="">Model: Default</option>
                {ollamaModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            )}
            <button
              type="button"
              className="btn btn-sm btn-primary"
              disabled={busyHere || llmTailorBusy || actionBusy}
              onClick={() => void handleTailorSection(section)}
            >
              {busyHere ? `Rewriting ${sectionTitle}...` : `Rewrite ${sectionTitle}`}
            </button>
          </div>
        </div>
        <AutoGrowTextarea
          minHeight={38}
          value={sectionPrompts[section] ?? ""}
          onChange={(e) =>
            setSectionPrompts((prev) => ({ ...prev, [section]: e.target.value }))
          }
          placeholder={placeholder}
        />
      </div>
    );
  };

  const renderSelectedJobDetailPanel = () => {
    if (!selectedJob) return null;
    const selectedStage = computeJobStage(selectedJob, jobProgressMap[selectedJob.id]);
    return (
      <div id="selected-job-detail-panel" className="card stack-md">
        <div className="row-between" style={{ alignItems: "flex-start" }}>
          <div className="stack-xs">
            <h2 style={{ margin: 0, fontSize: 20, letterSpacing: "-0.015em" }}>
              {selectedJob.analysis.title}
            </h2>
            <div className="muted" style={{ marginTop: 2 }}>
              <strong style={{ color: "var(--text-primary)" }}>
                {selectedJob.analysis.company}
              </strong>{" "}
              &middot; {selectedJob.analysis.location || "Unspecified Location"} &middot;{" "}
              <span className="pill">{trackName(selectedJob.analysis.role_track)}</span>{" "}
              <span className={selectedStage.pillClass}>{selectedStage.label}</span>
            </div>
            <div className="job-progress-track" style={{ maxWidth: 260 }}>
              {[1, 2, 3, 4].map((step) => (
                <span
                  key={step}
                  className={`job-progress-seg ${
                    selectedStage.stepCount >= step ? selectedStage.segClass : ""
                  }`}
                />
              ))}
            </div>
          </div>
          <div className="row-wrap">
            {selectedJob.url && (
              <a
                className="btn btn-success"
                href={selectedJob.url}
                target="_blank"
                rel="noreferrer"
              >
                Apply / Open Posting &#8599;
              </a>
            )}
            <select
              style={{ width: "auto" }}
              value={selectedJob.application_status}
              onChange={(e) =>
                void handleStatusChange(
                  selectedJob.id,
                  e.target.value as ApplicationStatus
                )
              }
            >
              <option value="ready">Status: Ready</option>
              <option value="resume_created">Status: Resume Created</option>
              <option value="applied">Status: Applied</option>
              <option value="screening">Status: Screening Call</option>
              <option value="interviewing">Status: Interviewing</option>
              <option value="offer">Status: Offer Received</option>
              <option value="rejected">Status: Rejected</option>
              <option value="skipped">Status: Skipped</option>
            </select>
            <button
              type="button"
              className="btn btn-danger-ghost"
              onClick={() => void handleDiscardJob(selectedJob.id)}
            >
              Discard
            </button>
          </div>
        </div>

        {/* Elaborate Role Snapshot Grid */}
        <div className="job-facts-grid">
          <div className="job-fact-card">
            <div className="job-fact-label">Compensation</div>
            <div className="job-fact-value">
              {formatCompensation(selectedJob)}
              {selectedJob.analysis.salary.meets_target === true && (
                <span className="pill pill-green" style={{ marginLeft: 6 }}>
                  Meets Target
                </span>
              )}
              {selectedJob.analysis.salary.meets_target === false && (
                <span className="pill pill-amber" style={{ marginLeft: 6 }}>
                  Below Target
                </span>
              )}
            </div>
            {selectedJob.analysis.salary.raw_snippet && (
              <div className="small-note">Listed: {selectedJob.analysis.salary.raw_snippet}</div>
            )}
          </div>

          <div className="job-fact-card">
            <div className="job-fact-label">Experience Required</div>
            <div className="job-fact-value">
              {selectedJob.analysis.yoe.min_years != null
                ? selectedJob.analysis.yoe.max_years != null
                  ? `${selectedJob.analysis.yoe.min_years}–${selectedJob.analysis.yoe.max_years} years`
                  : `${selectedJob.analysis.yoe.min_years}+ years`
                : "Not specified in posting"}
            </div>
            {selectedJob.analysis.yoe.raw_snippet && (
              <div className="small-note">{selectedJob.analysis.yoe.raw_snippet}</div>
            )}
          </div>

          <div className="job-fact-card">
            <div className="job-fact-label">Arrangement &amp; Schedule</div>
            <div className="job-fact-value">
              {selectedJob.work_type !== "unspecified"
                ? formatWorkTypeLabel(selectedJob.work_type)
                : "Arrangement Unspecified"}{" "}
              &middot; {formatJobTypeLabel(selectedJob.job_type)}
            </div>
            <div className="small-note">
              {selectedJob.analysis.work_auth === "h1b_ok"
                ? "H-1B sponsorship mentioned"
                : selectedJob.analysis.work_auth === "no_sponsorship"
                ? "No visa sponsorship / US Citizen only"
                : "Visa sponsorship not mentioned"}
            </div>
          </div>

          <div className="job-fact-card">
            <div className="job-fact-label">Published &amp; Source (ET)</div>
            <div className="job-fact-value">
              {formatPostedAtEastern(selectedJob.posted_at)}
            </div>
            <div className="small-note">
              Source: <strong>{formatSourceLabel(selectedJob.source)}</strong> &middot; Saved{" "}
              {formatEasternDateTime(selectedJob.created_at)}
            </div>
          </div>
        </div>

        {(selectedJob.analysis.expected_work.length > 0 ||
          selectedJob.analysis.detected_signals.length > 0 ||
          selectedJob.url ||
          selectedJob.raw_text) && (
          <div className="card-elevated stack-sm jd-reader-card">
            <div className="row-between">
              <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                <strong style={{ fontSize: 13.5 }}>
                  Job Description
                </strong>
                <div className="row-wrap" style={{ gap: 4 }}>
                  <button
                    type="button"
                    className={`chip ${jdViewMode === "highlights" ? "selected" : ""}`}
                    onClick={() => {
                      setJdViewMode("highlights");
                      setCollapsedCards((prev) => ({ ...prev, responsibilities: false }));
                    }}
                  >
                    Highlights ({selectedJob.analysis.expected_work.length})
                  </button>
                  <button
                    type="button"
                    className={`chip ${jdViewMode === "formatted" ? "selected" : ""}`}
                    onClick={() => {
                      setJdViewMode("formatted");
                      setCollapsedCards((prev) => ({ ...prev, responsibilities: false }));
                    }}
                  >
                    Formatted JD
                  </button>
                  <button
                    type="button"
                    className={`chip ${jdViewMode === "plain" ? "selected" : ""}`}
                    onClick={() => {
                      setJdViewMode("plain");
                      setCollapsedCards((prev) => ({ ...prev, responsibilities: false }));
                    }}
                  >
                    Plain Text
                  </button>
                </div>
              </div>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => toggleCard("responsibilities")}
              >
                {collapsedCards.responsibilities ? "▸ Expand" : "▾ Collapse"}
              </button>
            </div>
            {!collapsedCards.responsibilities && (
              <>
                {jdViewMode === "highlights" && (
                  <>
                    {selectedJob.analysis.expected_work.length > 0 ? (
                      <ul className="jd-highlights-list">
                        {selectedJob.analysis.expected_work.map((item, idx) => (
                          <li key={idx}>{decodeHtmlText(item)}</li>
                        ))}
                      </ul>
                    ) : (
                      <p className="muted" style={{ fontSize: 13 }}>No structured highlights extracted. Switch to Formatted JD above.</p>
                    )}

                    {selectedJob.analysis.detected_signals.length > 0 && (
                      <div className="row-wrap">
                        <span className="small-note">Engineering &amp; Seniority Signals:</span>
                        {selectedJob.analysis.detected_signals.map((sig) => (
                          <span key={sig} className="pill">
                            {sig}
                          </span>
                        ))}
                      </div>
                    )}
                  </>
                )}

                {jdViewMode === "formatted" && (
                  <div className="jd-reader" style={{ maxHeight: 380, overflowY: "auto", borderTop: "1px solid var(--border-subtle)", paddingTop: 8 }}>
                    {parsedJdBlocks.map((block, idx) => {
                      if (block.type === "heading") {
                        return (
                          <h4 key={idx} className="jd-heading">
                            {block.text}
                          </h4>
                        );
                      }
                      if (block.type === "bullets") {
                        return (
                          <ul key={idx} className="jd-list">
                            {block.items.map((item, itemIdx) => (
                              <li key={itemIdx}>{item}</li>
                            ))}
                          </ul>
                        );
                      }
                      return (
                        <p key={idx} className="jd-paragraph">
                          {block.text}
                        </p>
                      );
                    })}
                  </div>
                )}

                {jdViewMode === "plain" && (
                  <pre className="pre-box" style={{ maxHeight: 380, overflowY: "auto", borderTop: "1px solid var(--border-subtle)", paddingTop: 8 }}>
                    {decodeHtmlText(selectedJob.raw_text)}
                  </pre>
                )}

                {selectedJob.url && (
                  <div className="small-note" style={{ wordBreak: "break-all", paddingTop: 4 }}>
                    Direct Posting Link:{" "}
                    <a href={selectedJob.url} target="_blank" rel="noreferrer">
                      {selectedJob.url}
                    </a>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        <div
          className={`card stack-xs ${
            selectedJobSuitabilityReasons.length > 0 ? "suitability-card-flagged" : "suitability-card-clean"
          }`}
          style={{
            padding: "12px 16px",
            borderRadius: 10,
            background:
              selectedJobSuitabilityReasons.length > 0
                ? "rgba(255, 159, 10, 0.08)"
                : "rgba(48, 209, 88, 0.06)",
            border:
              selectedJobSuitabilityReasons.length > 0
                ? "1px solid rgba(255, 159, 10, 0.35)"
                : "1px solid rgba(48, 209, 88, 0.25)",
          }}
        >
          <div className="row-between" style={{ alignItems: "center" }}>
            <div className="row-wrap" style={{ gap: 8, alignItems: "center" }}>
              <strong
                style={{
                  fontSize: 13,
                  textTransform: "uppercase",
                  letterSpacing: "0.04em",
                  color:
                    selectedJobSuitabilityReasons.length > 0
                      ? "var(--accent-amber)"
                      : "var(--accent-green)",
                }}
              >
                Suitability Check
              </strong>
              {selectedJobSuitabilityReasons.length > 0 ? (
                <span className="pill pill-amber" style={{ fontSize: 11.5 }}>
                  {selectedJobSuitabilityReasons.length} reason{selectedJobSuitabilityReasons.length > 1 ? "s" : ""} flagged
                </span>
              ) : (
                <span className="pill pill-green" style={{ fontSize: 11.5 }}>
                  0 Blockers Detected · Suitable
                </span>
              )}
            </div>
            <button
              type="button"
              className="btn btn-sm"
              style={{ marginLeft: "auto", flexShrink: 0 }}
              onClick={() => toggleCard("suitability")}
            >
              {collapsedCards.suitability ? "▸ Expand" : "▾ Collapse"}
            </button>
          </div>

          {!collapsedCards.suitability && (
            <div style={{ marginTop: 8 }}>
              {selectedJobSuitabilityReasons.length === 0 ? (
                <div className="small-note" style={{ color: "var(--text-secondary)" }}>
                  ✓ Aligned with your target US tech hub preferences, visa criteria, compensation, and experience scope.
                </div>
              ) : (
                <div className="row-between" style={{ alignItems: "flex-start", gap: 12 }}>
                  <ul className="suitability-list" style={{ margin: "2px 0 0", paddingLeft: 18, flex: 1, fontSize: 13 }}>
                    {selectedJobSuitabilityReasons.map((reason, idx) => (
                      <li key={idx} style={{ marginBottom: 4 }}>
                        {reason}
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    className={`btn btn-sm ${
                      selectedJob && skillsAlignedJobs[selectedJob.id]
                        ? "btn-success"
                        : "btn-primary"
                    }`}
                    style={{ flexShrink: 0 }}
                    onClick={() => {
                      if (selectedJob && editedResume) {
                        const missing = (scoreReport?.missing_skills || liveReport?.missing_skills || []).map((s) => s.keyword);
                        const softExcluded = new Set(["mentorship", "leadership", "technical leadership", "agile", "scrum", "communication", "cross-functional", "ownership", "teamwork"]);
                        const cleanMissing = missing.filter((m) => !softExcluded.has(m.trim().toLowerCase()));

                        if (cleanMissing.length > 0) {
                          const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                          if (next.skills.length === 0) {
                            next.skills.push({ category: "Technical Skills", items: cleanMissing });
                          } else {
                            const targetCat = next.skills.find((c) => /tool|stack|system|data|cloud|framework|additional/i.test(c.category)) || next.skills[0];
                            const existingLows = new Set(targetCat.items.map((x) => x.toLowerCase()));
                            for (const sk of cleanMissing) {
                              if (!existingLows.has(sk.toLowerCase())) {
                                targetCat.items.push(sk);
                                existingLows.add(sk.toLowerCase());
                              }
                            }
                          }
                          setEditedResume(next);
                          recordManualEdit("Technical Skills", `Aligned ${cleanMissing.length} missing skill(s): ${cleanMissing.join(", ")}`);
                          setNotice(`Aligned ${cleanMissing.length} skill(s) (${cleanMissing.join(", ")}) into Technical Skills in Studio!`);
                        }
                        setSkillsAlignedJobs((prev) => ({ ...prev, [selectedJob.id]: true }));
                      }
                      setStudioSectionTab("skills");
                      setSectionEditorCollapsed(false);
                      setCollapsedCards((prev) => ({ ...prev, studio: false }));
                      window.setTimeout(() => {
                        document.getElementById("tailoring-studio-section-editor")?.scrollIntoView({
                          behavior: "smooth",
                          block: "start",
                        });
                      }, 50);
                    }}
                  >
                    {selectedJob && skillsAlignedJobs[selectedJob.id]
                      ? "✓ Skills Aligned in Studio"
                      : "⚡ Auto-Align Missing Skills into Studio"}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Resumes in Hand Selector & Quick 5-Yr Realistic Generator */}
        <div className="card-elevated stack-sm">
          <div className="row-between">
            <strong style={{ fontSize: 13.5 }}>Active Resumes</strong>
            <div className="row-wrap">
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setShowQuickBootstrap((v) => !v)}
              >
                {showQuickBootstrap ? "Close Base Generator" : "+ Auto-Generate Base Resume"}
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => onNavigateTab("resume")}
              >
                Manage Resumes
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => toggleCard("resumesInHand")}
              >
                {collapsedCards.resumesInHand ? "▸ Expand" : "▾ Collapse"}
              </button>
            </div>
          </div>

          {!collapsedCards.resumesInHand && (
            <>
          {resumes.length === 0 ? (
            <div className="row-between alert alert-info">
              <span>
                No base resume stored yet. Auto-generate a realistic starter resume (Summary,
                multi-employer experience with dates, 2+ Projects, Technical Skills, MS+BS Education)
                for <strong>{trackName(selectedJob.analysis.role_track)}</strong> right here, or
                upload your own.
              </span>
              <div className="row-wrap">
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={bootModeBusy !== null}
                  onClick={() => void handleQuickBootstrapResume(false)}
                >
                  {bootModeBusy === "fallback" ? "Generating..." : "Generate Without Ollama"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={bootModeBusy !== null}
                  onClick={() => void handleQuickBootstrapResume(true)}
                >
                  {bootModeBusy === "ollama" ? "Generating..." : "Generate With Ollama"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => onNavigateTab("resume")}
                >
                  Upload / Manual Form
                </button>
              </div>
            </div>
          ) : (
            <div className="row-wrap">
              {resumes.map((r) => {
                const matchesTrack = r.role_track === selectedJob.analysis.role_track;
                return (
                  <button
                    key={r.id}
                    type="button"
                    className={`chip ${selectedResumeId === r.id ? "selected" : ""}`}
                    onClick={() => void handleResumeSwitch(r.id)}
                  >
                    {r.name} ({trackName(r.role_track)})
                    {matchesTrack && r.is_base ? " · Recommended" : ""}
                  </button>
                );
              })}
            </div>
          )}

          {(showQuickBootstrap || resumes.length === 0) && (
            <div className="card stack-sm">
              <div className="row-between">
                <strong style={{ fontSize: 13 }}>
                  Quick Multi-Employer Base Generator (Summary + Experience + Projects + Skills + MS/BS)
                </strong>
                <span className="small-note">
                  Customize employers, dates &amp; degrees — generate with Ollama or Script.
                </span>
              </div>
              <div className="form-grid-3">
                <div>
                  <label>Candidate Name</label>
                  <input
                    value={bootName}
                    onChange={(e) => setBootName(e.target.value)}
                    placeholder="Alex Rivera"
                  />
                </div>
                <div>
                  <label>Role Track</label>
                  <select
                    value={bootRoleTrack || selectedJob.analysis.role_track}
                    onChange={(e) => setBootRoleTrack(e.target.value)}
                  >
                    {roleTracks.map((rt) => (
                      <option key={rt.id} value={rt.id}>
                        {rt.display_name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label>Years Experience</label>
                  <input
                    type="number"
                    min={1}
                    max={20}
                    value={bootYears}
                    onChange={(e) => setBootYears(Number(e.target.value) || 5)}
                  />
                </div>
              </div>
              <div className="form-grid-3">
                <div>
                  <label>Header City / State</label>
                  <input
                    value={bootLocation}
                    onChange={(e) => setBootLocation(e.target.value)}
                    placeholder={selectedJob.analysis.location || "New York, NY"}
                  />
                </div>
                <div>
                  <label>Extra Focus Skills (CSV)</label>
                  <input
                    value={bootFocusSkills}
                    onChange={(e) => setBootFocusSkills(e.target.value)}
                    placeholder="Python, Distributed Systems, PyTorch, RAG"
                  />
                </div>
                <div>
                  <label>Projects Count (Min 2)</label>
                  <select
                    value={bootProjectsCount}
                    onChange={(e) => setBootProjectsCount(Math.max(2, Number(e.target.value) || 2))}
                  >
                    {[2, 3, 4].map((n) => (
                      <option key={n} value={n}>
                        {n} Projects
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="card-elevated stack-sm">
                <div className="row-between">
                  <strong style={{ fontSize: 12.5 }}>
                    Employers &amp; Dates ({bootEmployers.length})
                  </strong>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() =>
                      setBootEmployers((prev) => [
                        ...prev,
                        {
                          company: "",
                          title: "Software Engineer",
                          location: bootLocation || "Austin, TX",
                          start_date: "Jan 2019",
                          end_date: "Feb 2021",
                          bullets_count: 5,
                        },
                      ])
                    }
                  >
                    + Add Employer
                  </button>
                </div>
                {bootEmployers.map((emp, idx) => (
                  <div key={idx} className="form-grid-3" style={{ alignItems: "end" }}>
                    <div>
                      <label>Employer #{idx + 1}</label>
                      <input
                        value={emp.company}
                        onChange={(e) => {
                          const next = [...bootEmployers];
                          next[idx] = { ...emp, company: e.target.value };
                          setBootEmployers(next);
                        }}
                        placeholder="e.g. Amazon"
                      />
                    </div>
                    <div>
                      <label>Title &amp; Location</label>
                      <div className="row-wrap" style={{ flexWrap: "nowrap", gap: 4 }}>
                        <input
                          value={emp.title || ""}
                          onChange={(e) => {
                            const next = [...bootEmployers];
                            next[idx] = { ...emp, title: e.target.value };
                            setBootEmployers(next);
                          }}
                          placeholder="Senior SWE"
                        />
                        <input
                          value={emp.location || ""}
                          onChange={(e) => {
                            const next = [...bootEmployers];
                            next[idx] = { ...emp, location: e.target.value };
                            setBootEmployers(next);
                          }}
                          placeholder="City, ST"
                          style={{ maxWidth: 110 }}
                        />
                      </div>
                    </div>
                    <div className="row-wrap" style={{ flexWrap: "nowrap", gap: 4 }}>
                      <input
                        value={emp.start_date || ""}
                        onChange={(e) => {
                          const next = [...bootEmployers];
                          next[idx] = { ...emp, start_date: e.target.value };
                          setBootEmployers(next);
                        }}
                        placeholder="Jan 2023"
                      />
                      <input
                        value={emp.end_date || ""}
                        onChange={(e) => {
                          const next = [...bootEmployers];
                          next[idx] = { ...emp, end_date: e.target.value };
                          setBootEmployers(next);
                        }}
                        placeholder="Present"
                      />
                      <select
                        value={emp.bullets_count || 5}
                        onChange={(e) => {
                          const next = [...bootEmployers];
                          next[idx] = { ...emp, bullets_count: Number(e.target.value) || 5 };
                          setBootEmployers(next);
                        }}
                        style={{ width: 66 }}
                        title="Bullets for this employer"
                      >
                        {[3, 4, 5, 6, 7, 8].map((n) => (
                          <option key={n} value={n}>
                            {n}b
                          </option>
                        ))}
                      </select>
                      {bootEmployers.length > 1 && (
                        <button
                          type="button"
                          className="btn btn-sm btn-danger-ghost"
                          onClick={() =>
                            setBootEmployers((prev) => prev.filter((_, i) => i !== idx))
                          }
                          title="Remove employer"
                        >
                          &times;
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              <div className="form-grid-2">
                <div>
                  <label>Graduate Degree (optional)</label>
                  <input
                    value={bootGradDegree}
                    onChange={(e) => setBootGradDegree(e.target.value)}
                    placeholder="Master of Science in Data Science (default)"
                  />
                </div>
                <div>
                  <label>Undergraduate Degree (optional)</label>
                  <input
                    value={bootUndergradDegree}
                    onChange={(e) => setBootUndergradDegree(e.target.value)}
                    placeholder="Bachelor of Science in Computer Science (default)"
                  />
                </div>
              </div>

              <div className="row-between">
                <span className="small-note">
                  Generates a tailored base ready to compare with this posting.
                </span>
                <div className="row-wrap">
                  <button
                    type="button"
                    className="btn btn-sm"
                    disabled={bootModeBusy !== null}
                    onClick={() => void handleQuickBootstrapResume(false)}
                  >
                    {bootModeBusy === "fallback"
                      ? "Generating (Script)..."
                      : "Generate Without Ollama (Script)"}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm btn-primary"
                    disabled={bootModeBusy !== null}
                    onClick={() => void handleQuickBootstrapResume(true)}
                  >
                    {bootModeBusy === "ollama"
                      ? "Generating (Ollama)..."
                      : "Generate With Local Ollama"}
                  </button>
                </div>
              </div>
            </div>
          )}
            </>
          )}
        </div>

        {/* Per-Job Skills Gap & JD Requirements Breakdown */}
        <div className="card-elevated stack-md">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", gap: 12, flexWrap: "wrap", rowGap: 8 }}>
            <div style={{ minWidth: 220, flex: "1 1 220px" }}>
              <strong style={{ fontSize: 14 }}>Skills &amp; Gaps</strong>
              <div className="small-note">
                {scoreReport
                  ? `Estimated length: ${scoreReport.estimated_pages} page(s) · ${selectedJob.analysis.weighted_skills.length} tracked JD skills · ${(scoreReport.resume_skills?.length ?? 0)} resume skills`
                  : `${selectedJob.analysis.weighted_skills.length} tracked role skills · ${allPostingSkills.length} total skills detected in posting`}
              </div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <button
                type="button"
                className={`btn btn-sm ${showAllSkills ? "btn-primary" : ""}`}
                onClick={() => setShowAllSkills((v) => !v)}
              >
                {showAllSkills
                  ? `Hide All Posting Skills (${allPostingSkills.length})`
                  : `View All Posting Skills (${allPostingSkills.length})`}
              </button>
              {scoreReport && (
                <>
                  <span className="pill pill-blue" style={{ fontSize: 13, padding: "3px 9px", whiteSpace: "nowrap" }}>
                    Base ATS: {scoreReport.overall_score}%
                  </span>
                  {tailorPreview && (
                    <span
                      className={`pill ${
                        tailorPreview.in_target_band
                          ? "pill-green"
                          : tailorPreview.tailored_score > 85
                          ? "pill-blue"
                          : "pill-amber"
                      }`}
                      style={{ fontSize: 13, padding: "3px 9px", whiteSpace: "nowrap" }}
                    >
                      Tailored ATS: {tailorPreview.tailored_score}%
                    </span>
                  )}
                </>
              )}
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => toggleCard("skillsGap")}
              >
                {collapsedCards.skillsGap ? "▸ Expand" : "▾ Collapse"}
              </button>
            </div>
          </div>

          {!collapsedCards.skillsGap && (
            <>
              {scoreReport ? (
                <div className="stack-md">
                  {scoreReport.resume_skills && scoreReport.resume_skills.length > 0 && (
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        All Skills Found on Your Active Resume ({scoreReport.resume_skills.length})
                      </div>
                      <div className="row-wrap">
                        {scoreReport.resume_skills.map((sk) => (
                          <span key={sk} className="pill">
                            {sk}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="form-grid-2">
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        Covered on Resume ({scoreReport.matched_skills.length})
                      </div>
                      <div className="row-wrap">
                        {scoreReport.matched_skills.length === 0 ? (
                          <span className="small-note">No direct keyword matches yet.</span>
                        ) : (
                          scoreReport.matched_skills.map((s) => (
                            <span key={s.keyword} className="pill pill-green">
                              {s.keyword} ({s.priority_label})
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        Missing Skills &amp; Gap Items ({scoreReport.missing_skills.length})
                      </div>
                      <div className="row-wrap">
                        {scoreReport.missing_skills.length === 0 ? (
                          <span className="pill pill-green">Zero skill gaps!</span>
                        ) : (
                          scoreReport.missing_skills.map((s) => (
                            <span key={s.keyword} className="pill pill-amber">
                              {s.keyword} ({s.priority_label})
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                  </div>

                  {scoreReport.missing_requirements && scoreReport.missing_requirements.length > 0 && (
                    <div className="card stack-xs" style={{ padding: "10px 12px" }}>
                      <strong style={{ fontSize: 12.5 }}>
                        Elaborate Missing Requirements &amp; Tailoring Targets ({scoreReport.missing_requirements.length})
                      </strong>
                      <ul className="req-gap-list">
                        {scoreReport.missing_requirements.map((req, idx) => (
                          <li key={idx}>{req}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ) : (
                <div className="row-wrap">
                  {selectedJob.analysis.weighted_skills.length === 0 ? (
                    <span className="small-note">No role-pack keywords matched in this JD.</span>
                  ) : (
                    selectedJob.analysis.weighted_skills.map((s) => (
                      <span
                        key={s.keyword}
                        className={s.tier === "core_must_have" ? "pill pill-blue" : "pill"}
                      >
                        {s.keyword} ({s.priority_label})
                      </span>
                    ))
                  )}
                </div>
              )}

              {showAllSkills && (
                <div className="skills-all-drawer stack-sm">
                  <div className="row-between">
                    <strong style={{ fontSize: 13 }}>
                      All Skills &amp; Technologies Listed in This Posting ({allPostingSkills.length})
                    </strong>
                    <span className="small-note">
                      Includes active role track weights + cross-track tech stack mentions
                    </span>
                  </div>
                  {allPostingSkills.length === 0 ? (
                    <div className="small-note">No recognized technical keywords extracted from text.</div>
                  ) : (
                    <div className="row-wrap">
                      {allPostingSkills.map((sk) => {
                        const norm = sk.keyword.toLowerCase();
                        const isMatched = matchedKeywordSet.has(norm);
                        const isMissing = missingKeywordSet.has(norm);
                        const pillClass = isMatched
                          ? "pill pill-green"
                          : isMissing
                          ? "pill pill-amber"
                          : sk.tier === "core_must_have"
                          ? "pill pill-blue"
                          : "pill";
                        return (
                          <span key={sk.keyword} className={pillClass}>
                            {sk.keyword}
                            {sk.jdMentions > 1 ? ` ×${sk.jdMentions}` : ""}
                            {sk.inRequired ? " · Req" : ""}
                            {sk.fromActiveTrack ? ` (${sk.priorityLabel})` : " (Stack)"}
                          </span>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </>
          )}
        </div>

        {/* Unified Live Resume Tailoring Studio & Formatted Paper Sheet */}
        {tailorPreview && editedResume && (
          <div className="card-elevated stack-md">
            {/* Split Top Header: Title & Badges Left, Pinned Collapse Button Right */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", width: "100%", gap: 10 }}>
              <div className="stack-xs" style={{ flex: 1 }}>
                <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                  <strong style={{ fontSize: 16 }}>
                    Tailoring Studio
                  </strong>
                  <span
                    className={`pill ${
                      tailorPreview.tailor_mode === "ollama_llm" ? "pill-green" : "pill-blue"
                    }`}
                    title="Active tailoring engine pipeline."
                  >
                    {tailorPreview.model_used
                      ? `Local Ollama (${tailorPreview.model_used})`
                      : tailorPreview.tailor_mode === "ollama_llm"
                      ? "Local Ollama"
                      : "Reasoning Script"}
                  </span>
                  {tailorPreview.in_target_band ? (
                    <span className="pill pill-green">80–85% Band Met</span>
                  ) : (
                    <span
                      className={`pill ${
                        tailorPreview.tailored_score > 85 ? "pill-blue" : "pill-amber"
                      }`}
                    >
                      {tailorPreview.tailored_score}% (Target: 80–85%)
                    </span>
                  )}
                  <span
                    className={`pill ${
                      tailorPreview.sanity_passed !== false ? "pill-green" : "pill-amber"
                    }`}
                  >
                    {tailorPreview.sanity_passed !== false
                      ? "Sanity Verified"
                      : "Sanity Check Warning"}
                  </span>
                  {(tailorPreview.humanized_count ?? 0) > 0 && (
                    <span className="pill">
                      Humanized: {tailorPreview.humanized_count} item(s)
                    </span>
                  )}
                </div>
                <div className="small-note">
                  Single-pass pipeline tailors Summary, Experience, Projects (&ge;2) &amp; Technical
                  Skills, removes robotic phrases (&ldquo;slashed&rdquo;, clichés), verifies timeline
                  plausibility, and calibrates match to 80–85%. Live edits re-score automatically.
                </div>
              </div>

              <button
                type="button"
                className="btn btn-sm"
                style={{ marginLeft: "auto", flexShrink: 0 }}
                onClick={() => toggleCard("studio")}
              >
                {collapsedCards.studio ? "▸ Expand" : "▾ Collapse"}
              </button>
            </div>

            {/* Dedicated Action Controls Bar */}
            <div className="row-between" style={{ flexWrap: "wrap", gap: 10, alignItems: "center", paddingTop: 4 }}>
              <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                {llmStatusInfo?.reachable ? (
                  <span className="pill pill-green" title={`Local Ollama active at ${llmStatusInfo.base_url}`}>
                    Ollama Online ({llmStatusInfo.configured_model || "Active"})
                  </span>
                ) : (
                  <span className="pill pill-amber" title="Ollama daemon is currently offline; automatic fallback active">
                    Ollama Offline (Auto-Failover Active)
                  </span>
                )}
                <select
                  style={{ width: "auto" }}
                  value={tailorStrategy}
                  onChange={(e) => setTailorStrategy(e.target.value as TailorStrategy)}
                  title="Choose AI tailoring engine"
                >
                  <option value="auto">Auto AI (Ollama + Failover)</option>
                  <option value="ollama">Local Ollama</option>
                  <option value="fallback_script">Reasoning Script Only</option>
                </select>
                {tailorStrategy !== "fallback_script" && (
                  <select
                    style={{ width: "auto" }}
                    value={selectedStudioModel || config?.values.llm_model || "mistral-nemo:latest"}
                    onChange={(e) => setSelectedStudioModel(e.target.value)}
                    title="Choose specific Ollama model for Tailoring Studio"
                  >
                    {(ollamaModels.length > 0
                      ? ollamaModels
                      : [config?.values.llm_model || "mistral-nemo:latest"]
                    ).map((m) => (
                      <option key={m} value={m}>
                        Model: {m}
                      </option>
                    ))}
                  </select>
                )}
              </div>

              <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                <button
                  type="button"
                  className={`btn btn-sm ${showDiffDrawer ? "btn-primary" : ""}`}
                  onClick={() => setShowDiffDrawer((v) => !v)}
                >
                  {showDiffDrawer ? "Hide Diff" : "Diff Audit"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={llmTailorBusy || actionBusy}
                  onClick={() => void handleRunUnifiedTailor()}
                >
                  {llmTailorBusy
                    ? "Tailoring & Verifying..."
                    : "Tailor Resume (80–85%)"}
                </button>
              </div>
            </div>

            {/* Animated Step-by-Step Tailoring Progress Bar */}
            {llmTailorBusy && (
              <div className="tailor-progress-banner">
                <div className="row-between">
                  <strong style={{ fontSize: 13, color: tailorStepIndex >= 5 ? "var(--accent-green)" : "var(--accent-blue)" }}>
                    {tailorStepIndex === 1 && "Step 1/5: Extracting Target Keywords & Posting Requirements..."}
                    {tailorStepIndex === 2 && "Step 2/5: Curating Heavy Base Sections & Redundant Projects..."}
                    {tailorStepIndex === 3 && "Step 3/5: Drafting & Humanizing Bullets (Zero Clichés)..."}
                    {tailorStepIndex === 4 && "Step 4/5: Calibrating ATS Match Score to 80–85% Target Band..."}
                    {tailorStepIndex >= 5 && "Step 5/5: 100% Complete · 9-Point Real-World Sanity Verified!"}
                  </strong>
                  <span className="mono" style={{ fontSize: 12 }}>{tailorStepIndex >= 5 ? "100%" : `${tailorStepIndex * 20}%`}</span>
                </div>
                <div className="tailor-progress-bar">
                  <div
                    className="tailor-progress-fill"
                    style={{
                      width: `${tailorStepIndex * 20}%`,
                      background: tailorStepIndex >= 5 ? "var(--accent-green)" : "var(--accent-blue)",
                      transition: "width 0.3s ease, background 0.3s ease",
                    }}
                  />
                </div>
                <div className="tailor-progress-steps">
                  <span>1. Keywords</span>
                  <span>2. Curation</span>
                  <span>3. Humanize</span>
                  <span>4. 80–85% Band</span>
                  <span style={{ color: tailorStepIndex >= 5 ? "var(--accent-green)" : undefined, fontWeight: tailorStepIndex >= 5 ? 700 : undefined }}>
                    5. 9 Sanity Checks (100%)
                  </span>
                </div>
              </div>
            )}

            {!collapsedCards.studio && (
              <>
                {/* Studio Controls: Single-Line Inline Dropdowns (Pages, Experience Bullets, Project Bullets, Blocked Words, Match City, Custom Prompt) */}
                <div className="card stack-sm" style={{ padding: "8px 12px" }}>
                  <div
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: 12,
                      rowGap: 8,
                    }}
                  >
                    {/* Control 1: Pages */}
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap", margin: 0 }}>
                        Pages:
                      </label>
                      <select
                        style={{ width: "auto", minWidth: 130, padding: "4px 8px", fontSize: 12.5 }}
                        value={autoSize ? "auto" : String(pageBudget)}
                        onChange={(e) => {
                          if (e.target.value === "auto") {
                            setAutoSize(true);
                            setCustomRoleBulletCounts([6, 6, 5]);
                          } else {
                            const pb = Number(e.target.value);
                            setPageBudget(pb);
                            setAutoSize(false);
                            if (pb === 1.0) setCustomRoleBulletCounts([4, 3, 2]);
                            else if (pb === 1.5) setCustomRoleBulletCounts([5, 4, 3]);
                            else if (pb === 2.0) setCustomRoleBulletCounts([6, 6, 5]);
                            else if (pb === 3.0) setCustomRoleBulletCounts([8, 7, 6, 5]);
                          }
                        }}
                        title="Pages determines total resume length and content density"
                      >
                        <option value="auto">Auto Seniority (6/6/5)</option>
                        <option value="1">1.0 Page (4/3/2)</option>
                        <option value="1.5">1.5 Pages (5/4/3)</option>
                        <option value="2">2.0 Pages (6/6/5)</option>
                        <option value="3">3.0 Pages (Deep Tech)</option>
                      </select>
                    </div>

                    {/* Control 2: Experience Bullets */}
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap", margin: 0 }}>
                        Experience:
                      </label>
                      <select
                        style={{ width: "auto", minWidth: 130, padding: "4px 8px", fontSize: 12.5 }}
                        value={autoSize ? "auto" : (bulletsPerExperience ?? 5)}
                        onChange={(e) => {
                          if (e.target.value === "auto") {
                            setAutoSize(true);
                            setCustomRoleBulletCounts([6, 6, 5]);
                          } else {
                            const val = Number(e.target.value);
                            setAutoSize(false);
                            setBulletsPerExperience(val);
                            setCustomRoleBulletCounts([val, val, val]);
                          }
                        }}
                        title="Number of bullets per experience entry"
                      >
                        <option value="auto">Auto Seniority (6/6/5)</option>
                        <option value="3">3 bullets / role</option>
                        <option value="4">4 bullets / role</option>
                        <option value="5">5 bullets / role</option>
                        <option value="6">6 bullets / role</option>
                        <option value="7">7 bullets / role</option>
                        <option value="8">8 bullets / role</option>
                      </select>
                    </div>

                    {/* Control 3: Project Bullets */}
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap", margin: 0 }}>
                        Projects:
                      </label>
                      <select
                        style={{ width: "auto", minWidth: 125, padding: "4px 8px", fontSize: 12.5 }}
                        value={bulletsPerProject}
                        onChange={(e) => {
                          const val = e.target.value === "" ? "" : Number(e.target.value);
                          setBulletsPerProject(val);
                        }}
                        title="Configure bullets per project entry in the tailored resume"
                      >
                        <option value="">Keep Original / Auto</option>
                        <option value="2">2 bullets / project</option>
                        <option value="3">3 bullets / project</option>
                        <option value="4">4 bullets / project</option>
                      </select>
                    </div>

                    {/* Control 4: Blocked Words Dropdown + Add custom word */}
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-secondary)", whiteSpace: "nowrap", margin: 0 }}>
                        Blocked:
                      </label>
                      <MultiSelectCheckboxDropdown
                        label=""
                        summaryText={`${avoidedWords.length} words`}
                        groups={buildAvoidedWordsGroups(avoidedWords)}
                        selected={avoidedWords}
                        onChange={setAvoidedWords}
                        quickActions={[
                          {
                            label: "Defaults",
                            onClick: () => setAvoidedWords([...DEFAULT_AVOIDED_AI_WORDS]),
                          },
                          { label: "Clear All", onClick: () => setAvoidedWords([]) },
                        ]}
                      />
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                        <input
                          value={customAvoidedStudioWord}
                          onChange={(e) => setCustomAvoidedStudioWord(e.target.value)}
                          placeholder="+ Block..."
                          style={{ fontSize: 11.5, padding: "3px 6px", width: 80 }}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              handleAddStudioAvoidedWord();
                            }
                          }}
                        />
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{ padding: "3px 7px", fontSize: 11.5, flexShrink: 0 }}
                          onClick={handleAddStudioAvoidedWord}
                        >
                          + Add
                        </button>
                      </div>
                    </div>

                    {/* Quick Toggles: Match City & Custom Prompt */}
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
                      <label className="checkbox-row" style={{ margin: 0, cursor: "pointer", fontSize: 12, whiteSpace: "nowrap" }}>
                        <input
                          type="checkbox"
                          checked={adaptLocation}
                          onChange={(e) => void handleToggleAdaptLocation(e.target.checked)}
                        />
                        <span>Match City</span>
                      </label>
                      <button
                        type="button"
                        className={`btn btn-sm ${showCustomPromptInput ? "btn-primary" : ""}`}
                        onClick={() => setShowCustomPromptInput((v) => !v)}
                        style={{ fontSize: 11.5, whiteSpace: "nowrap" }}
                      >
                        {showCustomPromptInput ? "Hide Notes" : "+ Custom Prompt"}
                      </button>
                    </div>
                  </div>

                  {/* Sections to Tailor Selector Block */}
                  <div
                    className="tailor-sections-block"
                    style={{
                      display: "flex",
                      flexWrap: "wrap",
                      alignItems: "center",
                      gap: 12,
                      padding: "8px 12px",
                      background: "rgba(255, 255, 255, 0.03)",
                      borderRadius: 8,
                      border: "1px solid var(--border-subtle)",
                      marginTop: 6,
                    }}
                  >
                    <strong style={{ fontSize: 12, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                      Sections to Tailor:
                    </strong>
                    <label className="checkbox-row" style={{ margin: 0, fontSize: 12.5, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={targetSections.includes("summary")}
                        onChange={(e) => {
                          setTargetSections((prev) =>
                            e.target.checked ? [...prev, "summary"] : prev.filter((s) => s !== "summary")
                          );
                        }}
                      />
                      <span>Summary</span>
                    </label>
                    <label className="checkbox-row" style={{ margin: 0, fontSize: 12.5, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={targetSections.includes("experience")}
                        onChange={(e) => {
                          setTargetSections((prev) =>
                            e.target.checked ? [...prev, "experience"] : prev.filter((s) => s !== "experience")
                          );
                        }}
                      />
                      <span>Experience Bullets</span>
                    </label>
                    <label className="checkbox-row" style={{ margin: 0, fontSize: 12.5, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={targetSections.includes("projects")}
                        onChange={(e) => {
                          setTargetSections((prev) =>
                            e.target.checked ? [...prev, "projects"] : prev.filter((s) => s !== "projects")
                          );
                        }}
                      />
                      <span>Projects (&ge; 2)</span>
                    </label>
                    <label className="checkbox-row" style={{ margin: 0, fontSize: 12.5, cursor: "pointer" }}>
                      <input
                        type="checkbox"
                        checked={targetSections.includes("skills")}
                        onChange={(e) => {
                          setTargetSections((prev) =>
                            e.target.checked ? [...prev, "skills"] : prev.filter((s) => s !== "skills")
                          );
                        }}
                      />
                      <span>Technical Skills</span>
                    </label>
                    <span
                      className="pill pill-blue"
                      title="Degrees, GPAs, and institutions remain 100% locked to prevent AI hallucination"
                    >
                      Education (Locked 🔒)
                    </span>
                    <span
                      className="pill pill-blue"
                      title="Company names, job titles, and employment dates remain 100% locked"
                    >
                      Company Names &amp; Dates (Locked 🔒)
                    </span>
                  </div>

                  {!autoSize && (
                    <div className="row-wrap" style={{ paddingTop: 4 }}>
                      <span className="small-note" style={{ fontWeight: 600 }}>
                        Variable Bullets / Company:
                      </span>
                      {editedResume.experience.map((exp, idx) => (
                        <label
                          key={exp.id || idx}
                          className="row-wrap"
                          style={{ gap: 4, margin: 0, fontSize: 12 }}
                        >
                          <span>{exp.company || `Role #${idx + 1}`}:</span>
                          <select
                            style={{ width: 64, padding: "3px 6px" }}
                            value={customRoleBulletCounts[idx] ?? exp.bullets.length}
                            onChange={(e) => {
                              const val = Number(e.target.value) || 5;
                              setCustomRoleBulletCounts((prev) => {
                                const next = [...prev];
                                while (next.length <= idx) next.push(5);
                                next[idx] = val;
                                return next;
                              });
                            }}
                          >
                            {[3, 4, 5, 6, 7, 8].map((n) => (
                              <option key={n} value={n}>
                                {n}
                              </option>
                            ))}
                          </select>
                        </label>
                      ))}
                      <select
                        style={{ width: "auto", padding: "3px 8px" }}
                        value={bulletsPerExperience ?? ""}
                        onChange={(e) =>
                          setBulletsPerExperience(
                            e.target.value === "" ? null : Number(e.target.value)
                          )
                        }
                        title="Fallback default bullet count"
                      >
                        {BULLET_COUNT_OPTIONS.map((opt) => (
                          <option key={String(opt.value)} value={opt.value}>
                            {opt.label}
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  {showCustomPromptInput && (
                    <div>
                      <label>Additional Tailoring Guidance for Ollama / Reasoning Script (optional)</label>
                      <input
                        value={customInstructions}
                        onChange={(e) => setCustomInstructions(e.target.value)}
                        placeholder="e.g., Highlight event-driven Kafka & FastAPI microservices; emphasize ownership"
                      />
                    </div>
                  )}
                </div>

                {tailorPreview.llm_notice && (
                  <div className="alert alert-info">{tailorPreview.llm_notice}</div>
                )}

                {tailorPreview.added_jd_skills && tailorPreview.added_jd_skills.length > 0 && (
                  <div className="alert" style={{ fontSize: 12.5 }}>
                    <strong>Integrated Missing Skills &amp; Terms (verify accuracy):</strong>{" "}
                    {tailorPreview.added_jd_skills.join(", ")}
                  </div>
                )}

                {/* Reasoning Trace & Real-World Plausibility Sanity Checks */}
                {((tailorPreview.sanity_checks && tailorPreview.sanity_checks.length > 0) ||
                  (tailorPreview.reasoning_steps && tailorPreview.reasoning_steps.length > 0)) && (
                  <div className="card stack-sm" style={{ padding: "10px 12px" }}>
                    <div className="row-between">
                      <div className="row-wrap">
                        <strong style={{ fontSize: 13 }}>
                          Sanity Checks &amp; Audit
                        </strong>
                        {tailorPreview.sanity_summary && (
                          <span className="small-note">{tailorPreview.sanity_summary}</span>
                        )}
                      </div>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => toggleCard("sanity")}
                      >
                        {collapsedCards.sanity ? "▸ Expand Checks" : "▾ Collapse Checks"}
                      </button>
                    </div>
                    {!collapsedCards.sanity && (
                      <div className="stack-sm">
                        {tailorPreview.sanity_checks && tailorPreview.sanity_checks.length > 0 && (
                          <div className="sanity-list">
                            {tailorPreview.sanity_checks.map((chk, idx) => (
                              <div
                                key={`${chk.check_id}-${idx}`}
                                className={`sanity-item ${
                                  chk.status === "warning" ? "warn" : "ok"
                                }`}
                              >
                                <div className="row-between" style={{ marginBottom: 2 }}>
                                  <strong>{chk.title}</strong>
                                  <span
                                    className={`pill ${
                                      chk.status === "passed"
                                        ? "pill-green"
                                        : chk.status === "repaired"
                                        ? "pill-blue"
                                        : "pill-amber"
                                    }`}
                                  >
                                    {chk.status === "repaired"
                                      ? "Auto-Repaired"
                                      : chk.status === "passed"
                                      ? "Passed"
                                      : "Warning"}
                                  </span>
                                </div>
                                <div className="small-note">{chk.detail}</div>
                              </div>
                            ))}
                          </div>
                        )}
                        {tailorPreview.reasoning_steps &&
                          tailorPreview.reasoning_steps.length > 0 && (
                            <div className="reasoning-list">
                              {tailorPreview.reasoning_steps.map((rs, idx) => (
                                <div key={`${rs.step}-${idx}`} className="reasoning-step">
                                  <strong>
                                    Step {rs.step} ({rs.phase}):
                                  </strong>{" "}
                                  {rs.decision}
                                </div>
                              ))}
                            </div>
                          )}
                      </div>
                    )}
                  </div>
                )}

                {showDiffDrawer && (
                  <div className="diff-drawer stack-sm">
                    <div className="row-between">
                      <strong style={{ fontSize: 13 }}>
                        Before &rarr; Tailored Audit Trail
                      </strong>
                      <span className="small-note">
                        Employers, titles, dates, and Education remain locked.
                      </span>
                    </div>
                    {tailorPreview.field_changes.map((fc, idx) => (
                      <div key={idx} className="small-note">
                        <strong>{fc.field_name}:</strong> {fc.before} &rarr;{" "}
                        <span style={{ color: "var(--text-primary)" }}>{fc.after}</span>
                      </div>
                    ))}
                    {tailorPreview.experience_comparisons.map((exp, expIdx) => (
                      <div key={exp.experience_id || expIdx} className="stack-xs" style={{ marginTop: 6 }}>
                        <strong style={{ fontSize: 12.5 }}>
                          {exp.title} @ {exp.company} ({exp.dates})
                        </strong>
                        {exp.bullets.map((b, bIdx) => (
                          <div key={b.bullet_id || bIdx} className="small-note" style={{ paddingLeft: 8, borderLeft: "2px solid var(--border-subtle)" }}>
                            <span className="pill" style={{ marginRight: 6 }}>{b.status}</span>
                            <span className="muted">{b.original_text}</span>
                            <div style={{ color: "#9fd4ff", marginTop: 2 }}>&rarr; {b.tailored_text}</div>
                          </div>
                        ))}
                      </div>
                    ))}
                  </div>
                )}

            <div className="stack-md">
              {/* Top: Clean Section-by-Section Inline Resume Studio (Collapsible) */}
              <div className="card stack-md">
                <div className="row-between" style={{ alignItems: "center" }}>
                  <div className="studio-tabs" role="tablist" aria-label="Resume Section Editor Tabs" style={{ flex: 1 }}>
                    <button
                      type="button"
                      className={`studio-tab ${studioSectionTab === "summary" ? "active" : ""}`}
                      onClick={() => { setStudioSectionTab("summary"); setSectionEditorCollapsed(false); }}
                    >
                      Summary
                    </button>
                    <button
                      type="button"
                      className={`studio-tab ${studioSectionTab === "experience" ? "active" : ""}`}
                      onClick={() => { setStudioSectionTab("experience"); setSectionEditorCollapsed(false); }}
                    >
                      Experience ({editedResume.experience.length})
                    </button>
                    <button
                      type="button"
                      className={`studio-tab ${studioSectionTab === "projects" ? "active" : ""}`}
                      onClick={() => { setStudioSectionTab("projects"); setSectionEditorCollapsed(false); }}
                    >
                      Projects ({editedResume.projects.length})
                    </button>
                    <button
                      type="button"
                      className={`studio-tab ${studioSectionTab === "skills" ? "active" : ""}`}
                      onClick={() => { setStudioSectionTab("skills"); setSectionEditorCollapsed(false); }}
                    >
                      Technical Skills ({editedResume.skills.length})
                    </button>
                    <button
                      type="button"
                      className={`studio-tab ${studioSectionTab === "education" ? "active" : ""}`}
                      onClick={() => { setStudioSectionTab("education"); setSectionEditorCollapsed(false); }}
                    >
                      Education ({editedResume.education.length})
                    </button>
                  </div>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setSectionEditorCollapsed((v) => !v)}
                  >
                    {sectionEditorCollapsed ? "▸ Edit Resume Sections" : "▾ Collapse Section Editor"}
                  </button>
                </div>

                {!sectionEditorCollapsed && (
                  <>
                    {sectionNotice && (
                      <div className="alert alert-info" style={{ padding: "8px 10px", fontSize: 12.5 }}>
                        {sectionNotice}
                      </div>
                    )}

                    {studioSectionTab === "summary" && (
                      <div className="stack-sm">
                        {renderSectionPromptBox(
                          "summary",
                          "Summary",
                          "Tell Ollama or Script how to tailor only your Summary (e.g. 'Emphasize 5+ years of distributed backend & Kafka experience cleanly in 3 lines')..."
                        )}
                        <label>
                          Tailored Summary for {selectedJob.analysis.title} @ {selectedJob.analysis.company}
                        </label>
                        <AutoGrowTextarea
                          minHeight={84}
                          value={editedResume.summary ?? ""}
                          onChange={(e) => updateTailoredSummary(e.target.value)}
                          placeholder="Concise 3-4 line summary aligned to the job description..."
                        />
                      </div>
                    )}

                    {studioSectionTab === "experience" && (
                      <div className="stack-md">
                        {renderSectionPromptBox(
                          "experience",
                          "Experience",
                          "Guide only Experience bullets (e.g. 'Surface FastAPI, Redis, and AWS observability work in my most recent role without touching employers/dates')..."
                        )}
                        {editedResume.experience.map((exp, expIdx) => (
                          <div key={exp.id || expIdx} className="stack-sm" style={{ paddingBottom: 10, borderBottom: "1px solid var(--border-subtle)" }}>
                            <div className="row-between">
                              <div>
                                <strong style={{ fontSize: 13.5 }}>
                                  {exp.title} @ {exp.company}
                                </strong>
                                <div className="small-note">
                                  {exp.start_date} – {exp.end_date} · {exp.location}
                                </div>
                              </div>
                              <div className="row-wrap">
                                <span className="pill">Company &amp; Dates Locked</span>
                                <button
                                  type="button"
                                  className="btn btn-sm btn-primary"
                                  onClick={() => setBulletBankTarget({ type: "exp", expIdx })}
                                  title="Browse & insert authentic bullets from your base resumes"
                                >
                                  + Bullet Bank
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-sm"
                                  onClick={() => addTailoredBullet(expIdx)}
                                >
                                  + Bullet
                                </button>
                              </div>
                            </div>
                            {exp.bullets.map((b, bIdx) => (
                              <div key={b.id || bIdx} className="row-wrap" style={{ alignItems: "flex-start", gap: 6 }}>
                                <AutoGrowTextarea
                                  minHeight={38}
                                  style={{ flex: 1 }}
                                  value={b.text}
                                  onChange={(e) => updateTailoredBullet(expIdx, bIdx, e.target.value)}
                                />
                                {exp.bullets.length > 1 && (
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-danger-ghost"
                                    onClick={() => removeTailoredBullet(expIdx, bIdx)}
                                    title="Remove bullet"
                                  >
                                    &times;
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}

                    {studioSectionTab === "projects" && (
                      <div className="stack-md">
                        {renderSectionPromptBox(
                          "projects",
                          "Projects",
                          "Customize only your Projects (e.g. 'Keep my core distributed systems project and weave Kubernetes + OpenTelemetry metrics from this JD')..."
                        )}
                        <div className="row-between">
                          <span className="small-note">
                            Tailored projects showcase capabilities aligned to this JD (&ge; 2 recommended).
                          </span>
                          <div className="row-wrap">
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              onClick={() => setBulletBankTarget({ type: "proj" })}
                            >
                              + From Project Bank
                            </button>
                            <button type="button" className="btn btn-sm" onClick={addProject}>
                              + Add Project
                            </button>
                          </div>
                        </div>
                        {editedResume.projects.map((proj, pIdx) => (
                          <div key={proj.id || pIdx} className="stack-sm" style={{ paddingBottom: 10, borderBottom: "1px solid var(--border-subtle)" }}>
                            <div className="form-grid-2">
                              <div>
                                <label>Project Name</label>
                                <input
                                  value={proj.name}
                                  onChange={(e) => updateProjectField(pIdx, { name: e.target.value })}
                                />
                              </div>
                              <div>
                                <label>Tech Stack (comma-separated)</label>
                                <input
                                  value={proj.tech_stack.join(", ")}
                                  onChange={(e) =>
                                    updateProjectField(pIdx, {
                                       tech_stack: e.target.value
                                        .split(",")
                                        .map((s) => s.trim())
                                        .filter(Boolean),
                                    })
                                  }
                                />
                              </div>
                            </div>
                            <div className="row-between" style={{ alignItems: "center", paddingTop: 4 }}>
                              <strong style={{ fontSize: 12.5, color: "var(--text-secondary)" }}>
                                Bullets ({proj.bullets.length})
                              </strong>
                              <button
                                type="button"
                                className="btn btn-sm"
                                onClick={() => addProjectBullet(pIdx)}
                              >
                                + Bullet
                              </button>
                            </div>
                            {proj.bullets.map((pb, pbIdx) => (
                              <div key={pb.id || pbIdx} className="row-wrap" style={{ alignItems: "flex-start", gap: 6 }}>
                                <AutoGrowTextarea
                                  minHeight={38}
                                  style={{ flex: 1 }}
                                  value={pb.text}
                                  onChange={(e) => updateProjectBullet(pIdx, pbIdx, e.target.value)}
                                  placeholder="Project achievement or implementation detail..."
                                />
                                {proj.bullets.length > 1 && (
                                  <button
                                    type="button"
                                    className="btn btn-sm btn-danger-ghost"
                                    onClick={() => removeProjectBullet(pIdx, pbIdx)}
                                    title="Remove project bullet"
                                  >
                                    &times;
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )}

                    {studioSectionTab === "skills" && (
                      <div className="stack-md">
                        {renderSectionPromptBox(
                          "skills",
                          "Technical Skills",
                          "Tailor only Technical Skills (e.g. 'Keep foundational 5y Python/AWS/Docker stack, add Spark & Kafka in proper capitalization, remove off-track noise')..."
                        )}
                        <div className="row-between">
                          <span className="small-note">
                            Comma-separated skills per category (exact JD terms lift ATS match).
                          </span>
                          <button type="button" className="btn btn-sm" onClick={addSkillCategory}>
                            + Add Category
                          </button>
                        </div>
                        {editedResume.skills.map((cat, catIdx) => (
                          <div key={catIdx} className="form-grid-2">
                            <div>
                              <label>Category</label>
                              <input
                                value={cat.category}
                                onChange={(e) =>
                                  updateSkillCategory(catIdx, e.target.value, cat.items.join(", "))
                                }
                              />
                            </div>
                            <div>
                              <label>Skills</label>
                              <AutoGrowTextarea
                                minHeight={38}
                                value={cat.items.join(", ")}
                                onChange={(e) =>
                                  updateSkillCategory(catIdx, cat.category, e.target.value)
                                }
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}

                    {studioSectionTab === "education" && (
                      <div className="stack-md">
                        {renderSectionPromptBox(
                          "education",
                          "Education",
                          "Customize education, coursework, or degree highlights (e.g. 'Emphasize Distributed Systems, Algorithms, and Cloud Systems coursework')..."
                        )}
                        <div className="row-between">
                          <span className="small-note">
                            Directly refine degrees, institutions, graduation dates, or coursework relevant to this role.
                          </span>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => {
                              const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                              next.education.push({
                                institution: "University",
                                degree: "Degree",
                                graduation_date: "Year",
                                location: "City, State",
                                coursework: [],
                              });
                              setEditedResume(next);
                            }}
                          >
                            + Add Education
                          </button>
                        </div>
                        {editedResume.education.map((edu, eIdx) => (
                          <div key={eIdx} className="card stack-sm" style={{ padding: "10px 12px" }}>
                            <div className="form-grid-2">
                              <div>
                                <label>Institution</label>
                                <input
                                  value={edu.institution}
                                  onChange={(e) => {
                                    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                                    next.education[eIdx].institution = e.target.value;
                                    setEditedResume(next);
                                  }}
                                />
                              </div>
                              <div>
                                <label>Degree</label>
                                <input
                                  value={edu.degree}
                                  onChange={(e) => {
                                    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                                    next.education[eIdx].degree = e.target.value;
                                    setEditedResume(next);
                                  }}
                                />
                              </div>
                            </div>
                            <div className="form-grid-2">
                              <div>
                                <label>Graduation Date</label>
                                <input
                                  value={edu.graduation_date}
                                  onChange={(e) => {
                                    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                                    next.education[eIdx].graduation_date = e.target.value;
                                    setEditedResume(next);
                                  }}
                                />
                              </div>
                              <div>
                                <label>Location</label>
                                <input
                                  value={edu.location ?? ""}
                                  onChange={(e) => {
                                    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                                    next.education[eIdx].location = e.target.value;
                                    setEditedResume(next);
                                  }}
                                />
                              </div>
                            </div>
                            <div>
                              <label>Coursework (comma-separated)</label>
                              <AutoGrowTextarea
                                minHeight={38}
                                value={(edu.coursework ?? []).join(", ")}
                                onChange={(e) => {
                                  const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
                                  next.education[eIdx].coursework = e.target.value
                                    .split(",")
                                    .map((s) => s.trim())
                                    .filter(Boolean);
                                  setEditedResume(next);
                                }}
                              />
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                )}
              </div>

              {/* Bottom: 100% Full-Width Live Formatted ATS Resume Sheet & Direct Download */}
              <div className="card stack-sm" style={{ width: "100%" }}>
                <LiveResumeSheet
                  resume={editedResume}
                  baseResume={selectedResume}
                  tailorPreview={tailorPreview}
                  liveReport={liveReport ?? tailorPreview.tailored_report}
                  exportResult={exportResult}
                  baseScore={scoreReport?.overall_score ?? tailorPreview.base_score}
                  editHistory={editHistoryByJob[selectedJob.id] ?? []}
                  pageBudget={autoSize ? (tailorPreview.page_budget ?? pageBudget) : pageBudget}
                  busy={actionBusy}
                  onExportFormat={(fmts) => void handleCreateResume(fmts)}
                  onDownloaded={() => markJobDownloaded(selectedJob.id)}
                  titleLabel={`Resume Preview — ${selectedJob.analysis.company}`}
                  onRevertToStep={handleRevertToStep}
                />
              </div>
            </div>
              </>
            )}
          </div>
        )}

        {/* Export Download Links */}
        {exportResult && (
          <div className="alert alert-success stack-sm">
            <div className="row-between">
              <strong>
                Resume Package Ready for Download ({selectedJob.analysis.company})
              </strong>
              <span className="pill pill-green">Tailored ATS Score: {exportResult.ats_score}%</span>
            </div>
            <div className="row-wrap">
              {exportResult.generated_files.map((fname) => (
                <a
                  key={fname}
                  className="btn btn-sm btn-success"
                  href={api.downloadArtifactUrl(exportResult.run_id, fname)}
                  download={fname}
                  onClick={() => markJobDownloaded(selectedJob.id)}
                >
                  Download {fname}
                </a>
              ))}
            </div>
          </div>
        )}

      </div>
    );
  };

  if (loadingJobs && jobs.length === 0 && filteredItems.length === 0 && discardedJobs.length === 0) {
    return <div className="muted" style={{ padding: 14 }}>Loading session postings...</div>;
  }

  return (
    <div className="stack-md">
      {error && <div className="alert alert-error">{error}</div>}
      {notice && (
        <div className="alert alert-success row-between">
          <span>{notice}</span>
          {workspaceView !== "saved" && jobs.length > 0 && (
            <button
              type="button"
              className="btn btn-sm btn-primary"
              onClick={() => setWorkspaceView("saved")}
            >
              Open Saved Jobs ({jobs.length}) &rarr;
            </button>
          )}
        </div>
      )}

      {/* Session View Switcher & Direct Excel Export */}
      <div className="row-between" style={{ flexWrap: "wrap", gap: 10, alignItems: "center", marginBottom: 6 }}>
        <div className="workspace-subtabs" style={{ marginBottom: 0 }}>
          <button
            type="button"
            className={`workspace-subtab ${workspaceView === "saved" ? "active" : ""}`}
            onClick={() => setWorkspaceView("saved")}
          >
            <span>Saved Jobs</span>
            <span className="pill pill-green mono">{jobs.length}</span>
          </button>
          <button
            type="button"
            className={`workspace-subtab ${workspaceView === "filtered" ? "active" : ""}`}
            onClick={() => setWorkspaceView("filtered")}
          >
            <span>Filtered by Rules</span>
            <span className="pill pill-amber mono">{autoFilteredItems.length}</span>
          </button>
          <button
            type="button"
            className={`workspace-subtab ${workspaceView === "seen" ? "active" : ""}`}
            onClick={() => setWorkspaceView("seen")}
          >
            <span>Seen / Skipped</span>
            <span className="pill pill-blue mono">{seenSkippedItems.length}</span>
          </button>
          <button
            type="button"
            className={`workspace-subtab ${workspaceView === "discarded" ? "active" : ""}`}
            onClick={() => setWorkspaceView("discarded")}
          >
            <span>Discarded</span>
            <span className="pill mono">{discardedJobs.length}</span>
          </button>
        </div>
      </div>

      {workspaceView === "saved" && (
        jobs.length === 0 ? (
          <div className="alert alert-info">
            No saved jobs in {session.name} yet.
            {filteredItems.length > 0
              ? ` Inspect "Filtered by Rules (${autoFilteredItems.length})" or "Seen / Skipped (${seenSkippedItems.length})" above to review skipped roles or add any back to your Saved List.`
              : " Select your sources and cities above, then click Scrape Target Roles."}
          </div>
        ) : (
          <div className="stack-md">
            {/* Accidental Switch Protection: Pending Tailored Downloads Banner */}
            {pendingDownloadJobs.length > 0 && (
              <div className="alert alert-info row-between" style={{ flexWrap: "wrap", gap: 8 }}>
                <span>
                  <strong>Tailored Resume Ready (Download Pending):</strong> You have{" "}
                  {pendingDownloadJobs.length} tailored draft
                  {pendingDownloadJobs.length > 1 ? "s" : ""} waiting for download.
                </span>
                <div className="row-wrap">
                  {pendingDownloadJobs.slice(0, 4).map((pj) => (
                    <button
                      key={pj.id}
                      type="button"
                      className="btn btn-sm btn-primary"
                      onClick={() => handleSelectJobCard(pj.id)}
                    >
                      Jump to {pj.analysis.company} &middot; {pj.analysis.title.slice(0, 26)} &rarr;
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Bulk Session Resume Generation Card */}
            <div className="card-elevated stack-sm">
              <div className="row-between">
                <div>
                  <strong style={{ fontSize: 14 }}>
                    Batch Generate Resumes for Saved Jobs ({jobs.length})
                  </strong>
                  <div className="small-note">
                    Automatically tailors, humanizes, sanity-checks, and calibrates every saved job
                    to 80–85% ATS match with seniority-based sizing (e.g., 2 pages &amp; 6/5 variable
                    bullets for 6–8+ YoE roles).
                  </div>
                </div>
                <button
                  type="button"
                  className={`btn btn-sm ${bulkOpen ? "btn-primary" : ""}`}
                  onClick={() => setBulkOpen((v) => !v)}
                >
                  {bulkOpen ? "▾ Close Batch Panel" : "▸ Open Batch Generator"}
                </button>
              </div>

              {bulkOpen && (
                <div className="stack-sm" style={{ paddingTop: 6 }}>
                  <div className="alert alert-info stack-xs" style={{ fontSize: 13, lineHeight: 1.45 }}>
                    <strong>What Batch Generator Does:</strong> Automatically loops through all saved postings in this session, tailors your resume to each job description targeting the optimal <strong>80–85% ATS match band</strong>, generates both PDF and Word DOCX formats, and saves each tailored draft directly into your workspace for immediate review.
                  </div>

                  <div className="form-grid-4">
                    <div>
                      <label>Batch Strategy</label>
                      <select
                        value={bulkStrategy}
                        onChange={(e) => setBulkStrategy(e.target.value as TailorStrategy)}
                      >
                        <option value="auto">Auto (Ollama &rarr; Script)</option>
                        <option value="ollama">Local Ollama Model</option>
                        <option value="fallback_script">Reasoning Script Only (Fast)</option>
                      </select>
                    </div>
                    <div style={{ display: "flex", alignItems: "flex-end" }}>
                      <label className="checkbox-row" style={{ margin: 0, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={bulkAutoSize}
                          onChange={(e) => setBulkAutoSize(e.target.checked)}
                        />
                        <span>Auto Seniority Sizing (2p + 6/5 bullets for 6–8y)</span>
                      </label>
                    </div>
                    <div style={{ display: "flex", alignItems: "flex-end" }}>
                      <label className="checkbox-row" style={{ margin: 0, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          checked={bulkIncludeAlready}
                          onChange={(e) => setBulkIncludeAlready(e.target.checked)}
                        />
                        <span>Regenerate Already-Created Jobs</span>
                      </label>
                    </div>
                    <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "flex-end", gap: 8 }}>
                      <button
                        type="button"
                        className="btn btn-primary"
                        disabled={bulkBusy || resumes.length === 0}
                        onClick={() => void handleBulkExportSession()}
                      >
                        {bulkBusy
                          ? "Generating Batch..."
                          : `Generate All Saved Resumes`}
                      </button>
                    </div>
                  </div>

                  {bulkBusy && (
                    <div className="tailor-progress-banner stack-xs" style={{ marginTop: 8 }}>
                      <div className="row-between">
                        <strong style={{ fontSize: 13, color: "var(--accent-blue)" }}>
                          Generating &amp; Calibrating Resumes for Saved Jobs (Targeting 80–85% ATS)...
                        </strong>
                        <span className="mono" style={{ fontSize: 12 }}>In Progress...</span>
                      </div>
                      <div className="tailor-progress-bar">
                        <div
                          className="tailor-progress-fill"
                          style={{
                            width: "100%",
                            background: "linear-gradient(90deg, var(--accent-blue), var(--accent-green))",
                          }}
                        />
                      </div>
                      <span className="small-note">Tailoring summaries, experiences &amp; tech stacks to each posting. Saved drafts will appear instantly when complete.</span>
                    </div>
                  )}

                  {bulkError && <div className="alert alert-error">{bulkError}</div>}

                  {bulkResult && (
                    <div className="card stack-sm" style={{ padding: "10px 12px" }}>
                      <div className="row-between">
                        <div className="row-wrap">
                          <span className="pill pill-green">
                            Succeeded: {bulkResult.succeeded_count} / {bulkResult.processed_count}
                          </span>
                          {bulkResult.failed_count > 0 && (
                            <span className="pill pill-amber">
                              Skipped / Failed: {bulkResult.failed_count}
                            </span>
                          )}
                        </div>
                        <a
                          className="btn btn-sm btn-success"
                          href={bulkResult.zip_download_url}
                          download={`Session_${session.id}_Tailored_Resumes.zip`}
                        >
                          Download All Resumes (.zip)
                        </a>
                      </div>

                      {bulkResult.items.length > 0 && (
                        <div style={{ maxHeight: 260, overflowY: "auto" }}>
                          <table className="data-table">
                            <thead>
                              <tr>
                                <th>Company &amp; Role</th>
                                <th>Track</th>
                                <th>Sizing</th>
                                <th>ATS Match</th>
                                <th>Downloads</th>
                              </tr>
                            </thead>
                            <tbody>
                              {bulkResult.items.map((item) => (
                                <tr key={`${item.job_id}-${item.run_id}`}>
                                  <td>
                                    <strong>{item.company}</strong> — {item.title}
                                  </td>
                                  <td>{trackName(item.role_track)}</td>
                                  <td className="mono">
                                    {item.page_budget}p ({item.bullets_per_role_counts.join("/")})
                                  </td>
                                  <td>
                                    <span
                                      className={`pill ${
                                        item.in_target_band ? "pill-green" : "pill-blue"
                                      }`}
                                    >
                                      {item.base_score}% &rarr; {item.tailored_score}%
                                    </span>
                                  </td>
                                  <td>
                                    <div className="row-wrap">
                                      {item.generated_files.map((fname) => (
                                        <a
                                          key={fname}
                                          className="btn btn-sm"
                                          href={api.downloadArtifactUrl(item.run_id, fname)}
                                          download={fname}
                                        >
                                          {fname.split(".").pop()?.toUpperCase()}
                                        </a>
                                      ))}
                                    </div>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Quick Pipeline Status Pile Bar */}
            <div className="row-between" style={{ alignItems: "center", marginBottom: 8, gap: 8 }}>
              <div className="row-wrap" style={{ gap: 6, alignItems: "center" }}>
                <span className="small-note" style={{ fontWeight: 700, color: "var(--text-secondary)", textTransform: "uppercase", fontSize: 11 }}>
                  Pipeline View:
                </span>
                <button
                  type="button"
                  className={`chip ${statusFilter === "all" ? "selected" : ""}`}
                  onClick={() => setStatusFilter("all")}
                >
                  All ({jobs.length})
                </button>
                <button
                  type="button"
                  className={`chip ${statusFilter === "ready" ? "selected" : ""}`}
                  onClick={() => setStatusFilter("ready")}
                >
                  Ready to Tailor ({statusCounts.ready || 0})
                </button>
                <button
                  type="button"
                  className={`chip ${statusFilter === "in_progress" ? "selected" : ""}`}
                  onClick={() => setStatusFilter("in_progress")}
                >
                  In Progress ({inProgressTotal})
                </button>
                <button
                  type="button"
                  className={`chip ${statusFilter === "applied" ? "selected" : ""}`}
                  onClick={() => setStatusFilter("applied")}
                >
                  Applied ({statusCounts.applied || 0})
                </button>
                <button
                  type="button"
                  className={`chip ${statusFilter === "unapplied_only" ? "selected" : ""}`}
                  onClick={() => setStatusFilter("unapplied_only")}
                  title="Skip all jobs that have already been applied to or are currently in interview stages"
                >
                  ⚡ Skip Applied ({jobs.filter((j) => !["applied", "screening", "interviewing", "offer"].includes(j.application_status)).length})
                </button>
                {statusCounts.resume_created > 0 && (
                  <button
                    type="button"
                    className={`chip ${statusFilter === "resume_created" ? "selected" : ""}`}
                    onClick={() => setStatusFilter("resume_created")}
                  >
                    Resume Created ({statusCounts.resume_created})
                  </button>
                )}
                {(statusCounts.interviewing > 0 || statusCounts.screening > 0) && (
                  <button
                    type="button"
                    className={`chip ${statusFilter === "interviewing" ? "selected" : ""}`}
                    onClick={() => setStatusFilter("interviewing")}
                  >
                    Interviewing ({(statusCounts.interviewing || 0) + (statusCounts.screening || 0)})
                  </button>
                )}
              </div>
            </div>

            {/* Sort & Multi-Faceted Filter Bar */}
            <div className="session-filter-bar">
              <select
                value={sortBy}
                onChange={(e) => {
                  const next = e.target.value as SavedSortMode;
                  if (next === "similar_selected" && selectedJob) {
                    setSelectedJobId(selectedJob.id);
                  }
                  setSortBy(next);
                }}
                aria-label="Sort saved jobs"
                title="Sort saved jobs"
              >
                <option value="latest">Sort: Latest Posted First</option>
                <option value="company_open_roles">Sort: Most Open Roles at Company</option>
                <option value="similar_selected">Sort: Similar to Selected Role</option>
                <option value="match_score">Sort: Best Match Score (%)</option>
                <option value="salary_high">Sort: Highest Listed Salary</option>
                <option value="oldest">Sort: Oldest Posted First</option>
                <option value="company_az">Sort: Company (A–Z)</option>
                <option value="title_az">Sort: Role Title (A–Z)</option>
              </select>

              <select
                value={companyFilter}
                onChange={(e) => setCompanyFilter(e.target.value)}
                aria-label="Filter by company"
              >
                <option value="all">
                  All Companies ({companyOpenRoles.sorted.length})
                </option>
                {companyOpenRoles.sorted.map((c) => (
                  <option key={c.company} value={c.company}>
                    {c.company} ({c.count} open)
                  </option>
                ))}
              </select>

              <select
                value={postedWithinFilter}
                onChange={(e) =>
                  setPostedWithinFilter(
                    e.target.value as "all" | "1h" | "6h" | "24h" | "3d" | "7d"
                  )
                }
                aria-label="Filter by posted window"
              >
                <option value="all">Any Posted Date</option>
                <option value="1h">Posted: Last 1 Hour</option>
                <option value="6h">Posted: Last 6 Hours</option>
                <option value="24h">Posted: Last 24 Hours</option>
                <option value="3d">Posted: Last 3 Days</option>
                <option value="7d">Posted: Last 7 Days</option>
              </select>

              <select
                value={roleFilter}
                onChange={(e) => setRoleFilter(e.target.value)}
                aria-label="Filter by role track"
              >
                <option value="all">All Role Tracks</option>
                {session.roles.map((r) => (
                  <option key={r.role_track} value={r.role_track}>
                    {trackName(r.role_track)} ({r.count})
                  </option>
                ))}
              </select>

              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                aria-label="Filter by source board"
              >
                <option value="all">All Sources</option>
                {availableSources.map((src) => (
                  <option key={src} value={src}>
                    Source: {formatSourceLabel(src)}
                  </option>
                ))}
              </select>

              <select
                value={workTypeFilter}
                onChange={(e) => setWorkTypeFilter(e.target.value)}
                aria-label="Filter by work mode"
              >
                <option value="all">All Work Modes</option>
                <option value="remote">Remote</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">On-Site</option>
                <option value="unspecified">Mode Unspecified</option>
              </select>

              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                aria-label="Filter by application status"
              >
                <option value="all">All Statuses ({jobs.length})</option>
                <option value="ready">Ready to Tailor ({statusCounts.ready || 0})</option>
                <option value="in_progress">In Progress ({inProgressTotal})</option>
                <option value="applied">Applied ({statusCounts.applied || 0})</option>
                <option value="resume_created">Resume Created ({statusCounts.resume_created || 0})</option>
                <option value="screening">Screening Call ({statusCounts.screening || 0})</option>
                <option value="interviewing">Interviewing ({statusCounts.interviewing || 0})</option>
                <option value="offer">Offer Received ({statusCounts.offer || 0})</option>
                <option value="rejected">Rejected ({statusCounts.rejected || 0})</option>
              </select>

              <select
                value={minMatchFilter}
                onChange={(e) => setMinMatchFilter(Number(e.target.value))}
                aria-label="Minimum relevance match"
              >
                <option value={0}>Any Match %</option>
                <option value={50}>Match &ge; 50%</option>
                <option value={70}>Match &ge; 70%</option>
                <option value={80}>Match &ge; 80%</option>
              </select>

              <div
                style={{
                  gridColumn: "span 4 / -1",
                  display: "flex",
                  alignItems: "center",
                  position: "relative",
                  minWidth: 260,
                }}
              >
                <input
                  style={{ width: "100%", paddingRight: jobQuery ? 30 : 10 }}
                  value={jobQuery}
                  onChange={(e) => setJobQuery(e.target.value)}
                  placeholder="🔍 Search jobs by company, role title, skills, or city..."
                  title="Filter listed jobs by company name, title, required tech, or location"
                />
                {jobQuery && (
                  <button
                    type="button"
                    onClick={() => setJobQuery("")}
                    style={{
                      position: "absolute",
                      right: 8,
                      background: "none",
                      border: "none",
                      cursor: "pointer",
                      color: "var(--text-secondary)",
                      fontSize: 14,
                    }}
                    title="Clear search"
                  >
                    &times;
                  </button>
                )}
              </div>
            </div>

            {/* Quick Toggle Chips & Active Filter Summary */}
            <div className="row-between">
              <div className="row-wrap" style={{ flex: 1, alignItems: "center" }}>
                {session.locations.length === 1 && (
                  <button
                    type="button"
                    className={`chip ${
                      selectedCities.includes(session.locations[0].location) ? "selected" : ""
                    }`}
                    onClick={() => {
                      const onlyCity = session.locations[0].location;
                      setSelectedCities((prev) =>
                        prev.includes(onlyCity) ? [] : [onlyCity]
                      );
                    }}
                  >
                    {session.locations[0].location} ({session.locations[0].count})
                  </button>
                )}
                {session.locations.length >= 2 && (
                  <div style={{ minWidth: 210, maxWidth: 320 }}>
                    <MultiSelectCheckboxDropdown
                      summaryText={
                        selectedCities.length === 0
                          ? `Cities: All (${session.locations.length})`
                          : selectedCities.length <= 2
                          ? `Cities: ${selectedCities.join(", ")}`
                          : `Cities: ${selectedCities.length} selected`
                      }
                      groups={[
                        {
                          title: `Cities in Session (${session.locations.length})`,
                          items: session.locations.map((loc) => ({
                            value: loc.location,
                            label: loc.location,
                            badge: String(loc.count),
                          })),
                        },
                      ]}
                      selected={selectedCities}
                      onChange={setSelectedCities}
                      searchPlaceholder="Search city..."
                      quickActions={[
                        {
                          label: "All Cities",
                          active: selectedCities.length === 0,
                          onClick: () => setSelectedCities([]),
                        },
                      ]}
                    />
                  </div>
                )}
                <span style={{ width: 1, height: 18, background: "var(--border-subtle)" }} />
                <button
                  type="button"
                  className={`chip ${onlyH1bConfirmed ? "selected" : ""}`}
                  onClick={() => setOnlyH1bConfirmed((v) => !v)}
                >
                  H-1B Confirmed Only
                </button>
                <button
                  type="button"
                  className={`chip ${onlyWithSalary ? "selected" : ""}`}
                  onClick={() => setOnlyWithSalary((v) => !v)}
                >
                  Salary Listed Only
                </button>
              </div>
              <div className="row-wrap">
                <span className="small-note">
                  Showing <strong>{filteredJobs.length}</strong> of {jobs.length}
                </span>
                {hasActiveSavedFilters && (
                  <button type="button" className="btn btn-sm" onClick={resetSavedFilters}>
                    Reset Filters
                  </button>
                )}
              </div>
            </div>

      {/* Dynamic Page Width, Split vs 4x4 Grid & Measurement Controls */}
      <div className="layout-toolbar">
        <div className="row-wrap">
          {onChangeViewportMode && (
            <div className="row-wrap" style={{ gap: 6 }}>
              <span className="small-note" style={{ fontWeight: 600 }}>Page Size:</span>
              {(["standard", "wide", "maximized"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={`chip ${viewportMode === mode ? "selected" : ""}`}
                  onClick={() => onChangeViewportMode(mode)}
                >
                  {mode === "standard"
                    ? "Standard"
                    : mode === "wide"
                    ? "Wide"
                    : "Maximized"}
                </button>
              ))}
            </div>
          )}

          <div className="row-wrap" style={{ gap: 6 }}>
            <span className="small-note" style={{ fontWeight: 600 }}>Layout:</span>
            <button
              type="button"
              className={`chip ${jobsViewLayout === "split" ? "selected" : ""}`}
              onClick={() => setJobsViewLayout("split")}
            >
              Straight Split (1/3 &middot; 2/3)
            </button>
            <button
              type="button"
              className={`chip ${jobsViewLayout === "grid" ? "selected" : ""}`}
              onClick={() => setJobsViewLayout("grid")}
            >
              Grid View ({gridCols}&times;{gridRows >= 99 ? "All" : gridRows})
            </button>
          </div>
        </div>

        <div className="row-wrap" style={{ gap: 10 }}>
          {jobsViewLayout === "split" ? (
            <>
              <div className="row-wrap" style={{ gap: 4 }}>
                <span className="small-note">Split:</span>
                {[25, 33, 40].map((pct) => (
                  <button
                    key={pct}
                    type="button"
                    className={`chip ${splitLeftPct === pct ? "selected" : ""}`}
                    onClick={() => setSplitLeftPct(pct)}
                  >
                    {pct}/{100 - pct}
                  </button>
                ))}
              </div>
              <label className="layout-slider-wrap" style={{ margin: 0 }}>
                <span>Left {splitLeftPct}%</span>
                <input
                  type="range"
                  min={22}
                  max={50}
                  value={splitLeftPct}
                  onChange={(e) => setSplitLeftPct(Number(e.target.value))}
                />
              </label>
              <label className="layout-slider-wrap" style={{ margin: 0 }}>
                <span>List H {splitListHeightPx}px</span>
                <input
                  type="range"
                  min={420}
                  max={1050}
                  step={20}
                  value={splitListHeightPx}
                  onChange={(e) => setSplitListHeightPx(Number(e.target.value))}
                />
              </label>
            </>
          ) : (
            <>
              <label className="layout-slider-wrap" style={{ margin: 0 }}>
                <span>Columns</span>
                <select
                  style={{ width: "auto", padding: "4px 8px" }}
                  value={gridCols}
                  onChange={(e) => setGridCols(Number(e.target.value))}
                >
                  {[2, 3, 4, 5].map((c) => (
                    <option key={c} value={c}>
                      {c} cols{c === 4 ? " (4x4)" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <label className="layout-slider-wrap" style={{ margin: 0 }}>
                <span>Visible Rows</span>
                <select
                  style={{ width: "auto", padding: "4px 8px" }}
                  value={gridRows}
                  onChange={(e) => setGridRows(Number(e.target.value))}
                >
                  <option value={2}>2 rows</option>
                  <option value={3}>3 rows</option>
                  <option value={4}>4 rows (4x4)</option>
                  <option value={99}>All rows</option>
                </select>
              </label>
            </>
          )}
        </div>
      </div>

      {filteredJobs.length === 0 ? (
        <div className="alert">
          No jobs match the current filters.{" "}
          {hasActiveSavedFilters && (
            <button type="button" className="btn btn-sm" onClick={resetSavedFilters}>
              Reset Filters
            </button>
          )}
        </div>
      ) : (
        <div
          className={jobsViewLayout === "grid" ? "stack-md" : "master-detail-grid"}
          style={
            jobsViewLayout === "split"
              ? ({ "--split-left-pct": `${splitLeftPct}%` } as CSSProperties)
              : undefined
          }
        >
          <div
            className={jobsViewLayout === "grid" ? "jobs-grid-view" : "job-list"}
            style={
              jobsViewLayout === "grid"
                ? ({
                    "--grid-cols": gridCols,
                    "--grid-max-h": gridRows >= 99 ? "none" : `${gridRows * 174}px`,
                  } as CSSProperties)
                : ({ "--job-list-max-h": `${splitListHeightPx}px` } as CSSProperties)
            }
          >
            {filteredJobs.map((job) =>
              renderJobPlacard(job, jobsViewLayout === "grid" ? "grid" : "list")
            )}
          </div>

          {renderSelectedJobDetailPanel()}
        </div>
      )}
          </div>
        )
      )}

      {(workspaceView === "filtered" || workspaceView === "seen") && (
        <div className="stack-md">
          <div className="alert alert-info">
            {workspaceView === "filtered" ? (
              <>
                <strong>Filtered by Config Rules:</strong> These postings failed one of your active
                filter rules (freshness, location, role title, H-1B sponsorship, compensation, or
                YoE). Check any roles you still want to pursue and click{" "}
                <strong>Add Selected to Saved List</strong> so you can tailor a resume for them.
              </>
            ) : (
              <>
                <strong>Seen / Already Skipped (Deduplication):</strong> These postings were skipped
                before fetching details because they matched your permanent history from earlier
                runs (<code>seen:saved</code>, <code>seen:auto_filtered</code>,{" "}
                <code>seen:discarded</code>) or appeared twice inside the same batch. Select any
                you want included in <em>this</em> session and add them back to Saved Jobs.
              </>
            )}
          </div>

          {activeAuditBase.length === 0 ? (
            <div className="alert">
              No {workspaceView === "filtered" ? "rule-filtered" : "seen / skipped"} postings were
              recorded in {session.name}.
            </div>
          ) : (
            <div className="stack-md">
              <div className="session-filter-bar">
                <select
                  value={auditSortBy}
                  onChange={(e) => setAuditSortBy(e.target.value as AuditSortMode)}
                  aria-label="Sort filtered jobs"
                >
                  <option value="latest_posted">Sort: Latest Posted First</option>
                  <option value="most_reasons">Sort: Most Unsuitability Reasons</option>
                  <option value="logged_recent">Sort: Most Recently Logged</option>
                  <option value="company_az">Sort: Company (A–Z)</option>
                  <option value="title_az">Sort: Role Title (A–Z)</option>
                </select>

                <select
                  value={auditLocationFilter}
                  onChange={(e) => setAuditLocationFilter(e.target.value)}
                  aria-label="Filter by location"
                >
                  <option value="all">All Locations ({activeAuditBase.length})</option>
                  {auditLocations.map((loc) => (
                    <option key={loc} value={loc}>
                      {loc}
                    </option>
                  ))}
                </select>

                <select
                  value={auditSourceFilter}
                  onChange={(e) => setAuditSourceFilter(e.target.value)}
                  aria-label="Filter by source"
                >
                  <option value="all">All Sources</option>
                  {auditSources.map((src) => (
                    <option key={src} value={src}>
                      Source: {src}
                    </option>
                  ))}
                </select>

                <input
                  value={auditQuery}
                  onChange={(e) => setAuditQuery(e.target.value)}
                  placeholder="Search title, company, city, reason..."
                />
              </div>

              <div className="row-between">
                <div className="row-wrap" style={{ flex: 1 }}>
                  <button
                    type="button"
                    className={`chip ${auditReasonFilter === "all" ? "selected" : ""}`}
                    onClick={() => setAuditReasonFilter("all")}
                  >
                    All Reasons ({activeAuditBase.length})
                  </button>
                  {auditReasonCounts.map((rc) => (
                    <button
                      key={rc.reason}
                      type="button"
                      className={`chip ${auditReasonFilter === rc.reason ? "selected" : ""}`}
                      onClick={() => setAuditReasonFilter(rc.reason)}
                    >
                      {rc.label} ({rc.count})
                    </button>
                  ))}
                </div>
                <span className="small-note">
                  Showing <strong>{visibleAuditItems.length}</strong> of {activeAuditBase.length}
                </span>
              </div>

              {/* Bulk Selection & Role Override Toolbar */}
              <div className="audit-toolbar">
                <div className="row-wrap">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setSelectedFilteredIds(visibleAuditItems.map((i) => i.id))}
                    disabled={visibleAuditItems.length === 0}
                  >
                    Select Visible ({visibleAuditItems.length})
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setSelectedFilteredIds([])}
                    disabled={selectedFilteredIds.length === 0}
                  >
                    Clear Selection
                  </button>
                  <span className="small-note">
                    <strong>{selectedFilteredIds.length}</strong> selected
                  </span>
                </div>

                <div className="row-wrap">
                  <select
                    value={promoteRoleOverride}
                    onChange={(e) => setPromoteRoleOverride(e.target.value)}
                    style={{ width: 210 }}
                    title="Optional role track when moving selected jobs to Saved"
                  >
                    <option value="">Role Track: Auto-detect</option>
                    {roleTracks.map((rt) => (
                      <option key={rt.id} value={rt.id}>
                        Track: {rt.display_name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-primary btn-sm"
                    disabled={selectedFilteredIds.length === 0 || promotingBusy}
                    onClick={() => void handlePromoteSelected(selectedFilteredIds)}
                  >
                    {promotingBusy
                      ? "Adding to Saved..."
                      : `Add Selected to Saved List (${selectedFilteredIds.length})`}
                  </button>
                </div>
              </div>

              {visibleAuditItems.length === 0 ? (
                <div className="alert">No items match the current reason or search filter.</div>
              ) : (
                <div className="audit-list">
                  {visibleAuditItems.map((item) => {
                    const checked = selectedFilteredIds.includes(item.id);
                    const isPromoted = item.promoted_job_id != null;
                    const codes = item.filter_reasons?.length
                      ? item.filter_reasons
                      : [item.filter_reason];
                    const labels = item.reason_labels?.length
                      ? item.reason_labels
                      : [item.reason_label];
                    const notes = item.suitability_notes ?? [];
                    return (
                      <div
                        key={item.id}
                        className={`audit-row ${checked ? "selected" : ""}`}
                        onClick={() => toggleFilteredSelection(item.id)}
                      >
                        <div className="row-between" style={{ alignItems: "flex-start", gap: 12 }}>
                          <div className="row-wrap" style={{ alignItems: "flex-start", flex: 1 }}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={() => toggleFilteredSelection(item.id)}
                              onClick={(e) => e.stopPropagation()}
                              style={{ marginTop: 4 }}
                            />
                            <div className="stack-sm" style={{ flex: 1, minWidth: 240 }}>
                              <div className="row-wrap">
                                <strong style={{ fontSize: 14.5 }}>{item.title}</strong>
                                {labels.map((lbl, idx) => {
                                  const code = codes[idx] || item.filter_reason;
                                  return (
                                    <span
                                      key={`${code}-${idx}`}
                                      className={
                                        item.category === "seen_skipped"
                                          ? "pill pill-blue"
                                          : "pill pill-amber"
                                      }
                                      title={code}
                                    >
                                      {lbl}
                                    </span>
                                  );
                                })}
                                {codes.length > 1 && (
                                  <span className="pill mono">{codes.length} reasons</span>
                                )}
                                {isPromoted && (
                                  <span className="pill pill-green">Added to Saved</span>
                                )}
                              </div>
                              <div className="small-note">
                                <strong style={{ color: "var(--text-primary)" }}>
                                  {item.company}
                                </strong>{" "}
                                &middot; {item.location || "Location Unspecified"} &middot;{" "}
                                <span>{formatSourceLabel(item.source)}</span>
                                {item.posted_at && (
                                  <> &middot; Posted {formatPostedAtEastern(item.posted_at)}</>
                                )}
                                <> &middot; Logged {formatEasternDateTime(item.created_at)}</>
                              </div>
                              {notes.length > 0 && (
                                <div className="suitability-box" style={{ marginTop: 2 }}>
                                  <div className="job-fact-label">
                                    Why Not Suitable ({notes.length}{" "}
                                    {notes.length === 1 ? "reason" : "reasons"})
                                  </div>
                                  <ul className="suitability-list">
                                    {notes.map((note, idx) => (
                                      <li key={idx}>{note}</li>
                                    ))}
                                  </ul>
                                </div>
                              )}
                              {item.raw_text_preview && (
                                <div className="audit-preview-snippet">
                                  {decodeHtmlText(item.raw_text_preview).slice(0, 260)}
                                  {item.raw_text_preview.length > 260 ? "..." : ""}
                                </div>
                              )}
                            </div>
                          </div>

                          <div
                            className="row-wrap"
                            onClick={(e) => e.stopPropagation()}
                            style={{ flexShrink: 0 }}
                          >
                            {item.url && (
                              <a
                                href={item.url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="btn btn-sm"
                              >
                                View Posting &nearr;
                              </a>
                            )}
                            <button
                              type="button"
                              className="btn btn-sm btn-primary"
                              disabled={promotingBusy}
                              onClick={() => void handlePromoteSelected([item.id])}
                            >
                              {isPromoted ? "Re-sync Saved" : "+ Save to List"}
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {workspaceView === "discarded" && (
        <div className="stack-md">
          {discardedJobs.length === 0 ? (
            <div className="alert">No discarded postings in {session.name}.</div>
          ) : (
            <div className="stack-md">
              <div className="audit-toolbar">
                <div className="row-wrap">
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setSelectedDiscardedIds(visibleDiscardedJobs.map((j) => j.id))}
                    disabled={visibleDiscardedJobs.length === 0}
                  >
                    Select All ({visibleDiscardedJobs.length})
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setSelectedDiscardedIds([])}
                    disabled={selectedDiscardedIds.length === 0}
                  >
                    Clear Selection
                  </button>
                  <select
                    value={discardedSortBy}
                    onChange={(e) => setDiscardedSortBy(e.target.value as DiscardedSortMode)}
                    style={{ width: 200 }}
                    aria-label="Sort discarded jobs"
                  >
                    <option value="latest">Sort: Latest Posted</option>
                    <option value="company_az">Sort: Company (A–Z)</option>
                    <option value="title_az">Sort: Role Title (A–Z)</option>
                  </select>
                  <div style={{ minWidth: 210 }}>
                    <input
                      value={auditQuery}
                      onChange={(e) => setAuditQuery(e.target.value)}
                      placeholder="Filter discarded jobs..."
                    />
                  </div>
                </div>
                <button
                  type="button"
                  className="btn btn-primary btn-sm"
                  disabled={selectedDiscardedIds.length === 0 || promotingBusy}
                  onClick={() => void handleRestoreDiscarded(selectedDiscardedIds)}
                >
                  {promotingBusy
                    ? "Restoring..."
                    : `Restore Selected to Saved (${selectedDiscardedIds.length})`}
                </button>
              </div>

              <div className="audit-list">
                {visibleDiscardedJobs.map((job) => {
                  const checked = selectedDiscardedIds.includes(job.id);
                  return (
                    <div
                      key={job.id}
                      className={`audit-row ${checked ? "selected" : ""}`}
                      onClick={() => toggleDiscardedSelection(job.id)}
                    >
                      <div className="row-between" style={{ gap: 12 }}>
                        <div className="row-wrap" style={{ flex: 1 }}>
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() => toggleDiscardedSelection(job.id)}
                            onClick={(e) => e.stopPropagation()}
                          />
                          <div className="stack-sm">
                            <div className="row-wrap">
                              <strong style={{ fontSize: 14.5 }}>{job.analysis.title}</strong>
                              <span className="pill">{trackName(job.analysis.role_track)}</span>
                              <span className="pill pill-red">Discarded</span>
                            </div>
                            <div className="small-note">
                              <strong style={{ color: "var(--text-primary)" }}>
                                {job.analysis.company}
                              </strong>{" "}
                              &middot; {job.analysis.location || "Unspecified"} &middot;{" "}
                              {formatSourceLabel(job.source)}
                              {job.posted_at && (
                                <> &middot; Posted {formatPostedAtEastern(job.posted_at)}</>
                              )}
                            </div>
                          </div>
                        </div>

                        <div className="row-wrap" onClick={(e) => e.stopPropagation()}>
                          {job.url && (
                            <a
                              href={job.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="btn btn-sm"
                            >
                              View Posting &nearr;
                            </a>
                          )}
                          <button
                            type="button"
                            className="btn btn-sm btn-primary"
                            disabled={promotingBusy}
                            onClick={() => void handleRestoreDiscarded([job.id])}
                          >
                            Restore to Saved
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Verified Base Bullet & Experience Bank Modal */}
      <CandidateBulletBankModal
        isOpen={bulletBankTarget !== null}
        onClose={() => setBulletBankTarget(null)}
        existingBullets={existingResumeBullets}
        targetRoleLabel={
          bulletBankTarget?.type === "exp" && bulletBankTarget.expIdx != null
            ? (editedResume?.experience[bulletBankTarget.expIdx]?.company || `Experience Role #${bulletBankTarget.expIdx + 1}`)
            : "Projects Section"
        }
        onSelectBullet={(bulletText, techTags) => {
          if (!editedResume || !bulletBankTarget) return;
          if (bulletBankTarget.type === "exp" && bulletBankTarget.expIdx != null) {
            const eIdx = bulletBankTarget.expIdx;
            const targetExp = editedResume.experience[eIdx];
            if (!targetExp) return;
            const newBullet = {
              id: `bank_b_${Date.now()}`,
              text: bulletText,
              provenance: "VERIFIED_BASE" as const,
              approved: true,
              tags: techTags,
            };
            const nextExp = { ...targetExp, bullets: [...targetExp.bullets, newBullet] };
            const nextExps = [...editedResume.experience];
            nextExps[eIdx] = nextExp;
            setEditedResume({ ...editedResume, experience: nextExps });
            recordManualEdit("Experience", `Inserted verified bullet into ${targetExp.company} from Bullet Bank`);
          } else if (bulletBankTarget.type === "proj") {
            const newBullet = {
              id: `bank_pb_${Date.now()}`,
              text: bulletText,
              provenance: "VERIFIED_BASE" as const,
              approved: true,
              tags: techTags,
            };
            if (editedResume.projects.length > 0) {
              const targetProj = editedResume.projects[0];
              const nextProj = { ...targetProj, bullets: [...targetProj.bullets, newBullet] };
              const nextProjs = [...editedResume.projects];
              nextProjs[0] = nextProj;
              setEditedResume({ ...editedResume, projects: nextProjs });
              recordManualEdit("Projects", `Inserted verified bullet into ${targetProj.name} from Bullet Bank`);
            } else {
              const newProj = {
                id: `bank_proj_${Date.now()}`,
                name: bulletText.length > 50 ? bulletText.slice(0, 48) + "..." : bulletText,
                tech_stack: techTags.length > 0 ? techTags : ["Python", "AWS", "Docker"],
                link: "github.com/portfolio/project",
                bullets: [newBullet],
              };
              setEditedResume({ ...editedResume, projects: [newProj] });
              recordManualEdit("Projects", "Added project from Candidate Project Bank");
            }
          }
        }}
      />
    </div>
  );
}
