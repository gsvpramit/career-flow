import { logActivity } from "./utils/activityLogger";
import type {
  AnalyticsReportResponse,
  ATSReport,
  BulkExportRequest,
  BulkExportResponse,
  CanonicalResume,
  ConfigResponse,
  ExportResponse,
  ExportRunItem,
  FlushDataRequest,
  FlushDataResult,
  HumanizeResumeResponse,
  JobDisposition,
  JobPostingResponse,
  LlmBenchmarkResponse,
  LlmStatusResponse,
  LlmTestResponse,
  LocationCatalogResponse,
  PromoteJobsResult,
  ResumeBootstrapRequest,
  ResumeBootstrapResponse,
  ResumeListResponse,
  ResumeRecordResponse,
  RoleTrackConfig,
  ScrapeBatchResult,
  ScrapeProgressResponse,
  ScrapeSessionSummary,
  SessionFilteredJobResponse,
  SessionSkillsGapResponse,
  SkillsGraphResponse,
  TailorPreviewResponse,
  TailorSectionRequest,
  TailorSectionResponse,
  TailorStrategy,
  ApplicationStatus,
} from "./types";

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      if (data?.detail) {
        message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch {
      // ignore non-json body
    }
    logActivity({
      level: "error",
      source: path.includes("tailor") ? "Tailoring Studio" : path.includes("scrape") ? "Scraper Engine" : "Backend API",
      title: `HTTP ${res.status} on ${path}`,
      message,
      details: `Method: ${init?.method || "GET"}\nEndpoint: ${path}\nStatus: ${res.status} ${res.statusText}\nPayload: ${init?.body ? String(init.body) : "none"}\nResponse: ${message}`,
    });
    throw new Error(message);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export const api = {
  getConfig: () => apiRequest<ConfigResponse>("/api/config"),

  updateConfig: (updates: Record<string, unknown>) =>
    apiRequest<ConfigResponse>("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates }),
    }),

  getRoleTracks: () => apiRequest<RoleTrackConfig[]>("/api/config/role-tracks"),

  updateRoleTrack: (
    trackId: string,
    payload: {
      display_name?: string;
      aliases?: string[];
      description?: string;
      keywords?: Record<string, string[]>;
    }
  ) =>
    apiRequest<RoleTrackConfig>(`/api/config/role-tracks/${encodeURIComponent(trackId)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  listResumes: () => apiRequest<ResumeListResponse>("/api/resumes"),

  createResume: (payload: {
    name: string;
    role_track: string;
    is_base: boolean;
    content: CanonicalResume;
  }) =>
    apiRequest<ResumeRecordResponse>("/api/resumes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  updateResume: (
    resumeId: number,
    payload: {
      name: string;
      role_track: string;
      is_base: boolean;
      content: CanonicalResume;
    }
  ) =>
    apiRequest<ResumeRecordResponse>(`/api/resumes/${resumeId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  deleteResume: (resumeId: number) =>
    apiRequest<void>(`/api/resumes/${resumeId}`, { method: "DELETE" }),

  uploadResumeFile: (file: File, name: string, roleTrack: string, isBase = true) => {
    const form = new FormData();
    form.append("file", file);
    form.append("name", name);
    form.append("role_track", roleTrack);
    form.append("is_base", String(isBase));
    return apiRequest<ResumeRecordResponse>("/api/resumes/upload", {
      method: "POST",
      body: form,
    });
  },

  getLocations: () => apiRequest<LocationCatalogResponse>("/api/config/locations"),

  listSessions: () => apiRequest<ScrapeSessionSummary[]>("/api/sessions"),

  createSession: (name: string, postedWithin?: string) =>
    apiRequest<ScrapeSessionSummary>("/api/sessions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, posted_within: postedWithin || undefined }),
    }),

  scrapeSessionBatch: (
    sessionId: number,
    payload: {
      posted_within?: string;
      role_tracks?: string[];
      locations?: string[];
      sources?: string[];
      company_boards?: string[];
    }
  ) =>
    apiRequest<ScrapeBatchResult>(`/api/sessions/${sessionId}/scrape`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  startSessionScrape: (
    sessionId: number,
    payload: {
      posted_within?: string;
      role_tracks?: string[];
      locations?: string[];
      sources?: string[];
      company_boards?: string[];
    }
  ) =>
    apiRequest<ScrapeProgressResponse>(`/api/sessions/${sessionId}/scrape/start`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getScrapeProgress: (sessionId: number) =>
    apiRequest<ScrapeProgressResponse>(`/api/sessions/${sessionId}/scrape/progress`),

  stopSessionScrape: (sessionId: number) =>
    apiRequest<ScrapeProgressResponse>(`/api/sessions/${sessionId}/scrape/stop`, {
      method: "POST",
    }),

  listSessionFilteredJobs: (sessionId: number, category?: "auto_filtered" | "seen_skipped") =>
    apiRequest<SessionFilteredJobResponse[]>(
      category
        ? `/api/sessions/${sessionId}/filtered?category=${encodeURIComponent(category)}`
        : `/api/sessions/${sessionId}/filtered`
    ),

  promoteFilteredJobs: (
    sessionId: number,
    filteredIds: number[],
    roleTrackOverride?: string
  ) =>
    apiRequest<PromoteJobsResult>(`/api/sessions/${sessionId}/filtered/promote`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filtered_ids: filteredIds,
        role_track_override: roleTrackOverride || null,
      }),
    }),

  restoreDiscardedJobs: (sessionId: number, jobIds: number[]) =>
    apiRequest<PromoteJobsResult>(`/api/sessions/${sessionId}/discarded/restore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_ids: jobIds }),
    }),

  listJobs: (sessionId?: number | null, includeDiscarded = false) => {
    const params = new URLSearchParams();
    if (sessionId != null) params.set("session_id", String(sessionId));
    if (includeDiscarded) params.set("include_discarded", "true");
    const qs = params.toString();
    return apiRequest<JobPostingResponse[]>(qs ? `/api/jobs?${qs}` : "/api/jobs");
  },

  ingestJob: (payload: {
    session_id?: number;
    url?: string;
    raw_text?: string;
    company_override?: string;
    title_override?: string;
    location_override?: string;
    role_track?: string;
  }) =>
    apiRequest<JobPostingResponse>("/api/jobs/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  patchJob: (
    jobId: number,
    payload: {
      disposition?: JobDisposition;
      application_status?: ApplicationStatus;
      application_notes?: string;
    }
  ) =>
    apiRequest<JobPostingResponse>(`/api/jobs/${jobId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  scoreJob: (jobId: number, resumeId?: number) =>
    apiRequest<ATSReport>("/api/jobs/score", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job_id: jobId, resume_id: resumeId ?? null }),
    }),

  previewTailor: (
    jobId: number,
    resumeId?: number,
    adaptLocation = true,
    useLlm?: boolean,
    rehumanize = false,
    options?: {
      tailorStrategy?: TailorStrategy;
      bulletsPerExperience?: number | null;
      bulletsPerRoleCounts?: number[] | null;
      bulletsPerProject?: number | null;
      autoSize?: boolean;
      pageBudget?: number | null;
      avoidedWords?: string[];
      customInstructions?: string;
      targetScore?: number;
      targetScoreMin?: number;
      targetScoreMax?: number;
      llmModel?: string;
      targetSections?: string[];
    }
  ) =>
    apiRequest<TailorPreviewResponse>("/api/tailor/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        resume_id: resumeId ?? null,
        adapt_location: adaptLocation,
        use_llm: useLlm ?? null,
        tailor_strategy: options?.tailorStrategy ?? "auto",
        rehumanize,
        bullets_per_experience: options?.bulletsPerExperience ?? null,
        bullets_per_role_counts: options?.bulletsPerRoleCounts ?? null,
        bullets_per_project: options?.bulletsPerProject ?? null,
        auto_size: options?.autoSize ?? false,
        page_budget: options?.pageBudget ?? null,
        avoided_words: options?.avoidedWords ?? null,
        custom_instructions: options?.customInstructions ?? null,
        target_score: options?.targetScore ?? options?.targetScoreMin ?? 80,
        target_score_min: options?.targetScoreMin ?? 80,
        target_score_max: options?.targetScoreMax ?? 85,
        llm_model: options?.llmModel ?? null,
        target_sections: options?.targetSections ?? null,
      }),
    }),

  bulkExportSession: (sessionId: number, payload: BulkExportRequest) =>
    apiRequest<BulkExportResponse>(`/api/sessions/${sessionId}/bulk-export`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  scoreDraftResume: (jobId: number, draftResume: CanonicalResume, resumeId?: number) =>
    apiRequest<ATSReport>("/api/tailor/score-draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        resume_id: resumeId ?? null,
        draft_resume: draftResume,
      }),
    }),

  tailorSection: (payload: TailorSectionRequest) =>
    apiRequest<TailorSectionResponse>("/api/tailor/section", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  humanizeResume: (
    resume: CanonicalResume,
    jobId?: number | null,
    useLlm = false,
    avoidedWords?: string[]
  ) =>
    apiRequest<HumanizeResumeResponse>("/api/tailor/humanize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume,
        job_id: jobId ?? null,
        use_llm: useLlm,
        avoided_words: avoidedWords ?? null,
      }),
    }),

  bootstrapResume: (payload: ResumeBootstrapRequest) =>
    apiRequest<ResumeBootstrapResponse>("/api/resumes/bootstrap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),

  getLlmStatus: () => apiRequest<LlmStatusResponse>("/api/config/llm/status"),

  testLlm: (model?: string | null, baseUrl?: string | null) =>
    apiRequest<LlmTestResponse>("/api/config/llm/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: model ?? null, base_url: baseUrl ?? null }),
    }),

  benchmarkLlm: (models?: string[] | null, baseUrl?: string | null) =>
    apiRequest<LlmBenchmarkResponse>("/api/config/llm/benchmark", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ models: models ?? null, base_url: baseUrl ?? null }),
    }),

  exportResume: (
    jobId: number,
    resumeId?: number,
    tailoredResume?: CanonicalResume,
    formats?: ("pdf" | "docx")[],
    pageBudget?: number | null
  ) =>
    apiRequest<ExportResponse>("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        resume_id: resumeId ?? null,
        tailored_resume: tailoredResume ?? null,
        formats: formats ?? null,
        page_budget: pageBudget ?? null,
      }),
    }),

  listExportRuns: () => apiRequest<ExportRunItem[]>("/api/export/runs"),

  downloadArtifactUrl: (runId: number, filename: string) =>
    `/api/export/runs/${runId}/download/${encodeURIComponent(filename)}`,

  getSkillsGap: (sessionId?: number | null) =>
    apiRequest<SessionSkillsGapResponse>(
      sessionId != null ? `/api/skills-gap?session_id=${sessionId}` : "/api/skills-gap"
    ),

  getReports: (sessionId?: number | null) =>
    apiRequest<AnalyticsReportResponse>(
      sessionId != null ? `/api/reports?session_id=${sessionId}` : "/api/reports"
    ),

  htmlReportUrl: (sessionId?: number | null) =>
    sessionId != null ? `/api/reports/html?session_id=${sessionId}` : "/api/reports/html",

  excelReportUrl: (sessionId?: number | null) =>
    sessionId != null ? `/api/reports/excel?session_id=${sessionId}` : "/api/reports/excel",

  getSkillsGraph: (sessionId?: number | null) =>
    apiRequest<SkillsGraphResponse>(
      sessionId != null ? `/api/reports/skills-graph?session_id=${sessionId}` : "/api/reports/skills-graph"
    ),

  clearSeenHistory: (scope: "discarded" | "auto_filtered" | "all") =>
    apiRequest<{ cleared: number }>(`/api/seen/clear-discarded?scope=${scope}`, {
      method: "POST",
    }),

  flushData: (payload: FlushDataRequest) =>
    apiRequest<FlushDataResult>("/api/data/flush", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
};
