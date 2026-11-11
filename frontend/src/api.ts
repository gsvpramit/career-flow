import type {
  AnalyticsReportResponse,
  ATSReport,
  CanonicalResume,
  ConfigResponse,
  ExportResponse,
  ExportRunItem,
  JobDisposition,
  JobPostingResponse,
  ResumeListResponse,
  ResumeRecordResponse,
  RoleTrackConfig,
  ScrapeBatchResult,
  ScrapeSessionSummary,
  SessionSkillsGapResponse,
  TailorPreviewResponse,
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

  listJobs: (sessionId?: number | null) =>
    apiRequest<JobPostingResponse[]>(
      sessionId != null ? `/api/jobs?session_id=${sessionId}` : "/api/jobs"
    ),

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

  previewTailor: (jobId: number, resumeId?: number, adaptLocation = true) =>
    apiRequest<TailorPreviewResponse>("/api/tailor/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        resume_id: resumeId ?? null,
        adapt_location: adaptLocation,
      }),
    }),

  exportResume: (
    jobId: number,
    resumeId?: number,
    tailoredResume?: CanonicalResume,
    formats?: ("pdf" | "docx")[]
  ) =>
    apiRequest<ExportResponse>("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        job_id: jobId,
        resume_id: resumeId ?? null,
        tailored_resume: tailoredResume ?? null,
        formats: formats ?? null,
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

  clearSeenHistory: (scope: "discarded" | "auto_filtered" | "all") =>
    apiRequest<{ cleared: number }>(`/api/seen/clear-discarded?scope=${scope}`, {
      method: "POST",
    }),
};
