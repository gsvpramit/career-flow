import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type {
  ApplicationStatus,
  ATSReport,
  CanonicalResume,
  ConfigResponse,
  ExportResponse,
  JobPostingResponse,
  ResumeListResponse,
  RoleTrackConfig,
  ScrapeBatchResult,
  ScrapeSessionSummary,
  TabId,
  TailorPreviewResponse,
} from "../types";

interface JobPanelProps {
  config: ConfigResponse | null;
  sessions: ScrapeSessionSummary[];
  activeSessionId: number | null;
  onSelectSession: (id: number) => void;
  roleTracks: RoleTrackConfig[];
  resumeState: ResumeListResponse | null;
  onSessionsChanged: (selectId?: number) => Promise<void>;
  onNavigateTab: (tab: TabId) => void;
}

const FRESHNESS_OPTIONS = [
  { value: "1h", label: "Less than 1 hour ago" },
  { value: "12h", label: "Less than 12 hours ago" },
  { value: "24h", label: "Less than 24 hours ago" },
  { value: "7d", label: "Past 7 days" },
  { value: "any", label: "Any time" },
];

const STATUS_BADGE_CLASS: Record<ApplicationStatus, string> = {
  ready: "pill",
  resume_created: "pill pill-blue",
  applied: "pill pill-green",
  skipped: "pill pill-amber",
};

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

export function JobPanel({
  config,
  sessions,
  activeSessionId,
  onSelectSession,
  roleTracks,
  resumeState,
  onSessionsChanged,
  onNavigateTab,
}: JobPanelProps) {
  const [jobs, setJobs] = useState<JobPostingResponse[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<number | null>(null);
  const [locationFilter, setLocationFilter] = useState<string>("all");
  const [roleFilter, setRoleFilter] = useState<string>("all");

  // Session creation & batch scrape state
  const [newSessionName, setNewSessionName] = useState("");
  const [freshness, setFreshness] = useState<string>(
    config?.values.posted_within_default || "24h"
  );
  const [scraping, setScraping] = useState(false);
  const [batchResult, setBatchResult] = useState<ScrapeBatchResult | null>(null);

  // Manual ingest drawer
  const [showManualDrawer, setShowManualDrawer] = useState(false);
  const [manualUrl, setManualUrl] = useState("");
  const [manualText, setManualText] = useState("");
  const [manualCompany, setManualCompany] = useState("");
  const [manualTitle, setManualTitle] = useState("");
  const [manualLocation, setManualLocation] = useState("");
  const [ingesting, setIngesting] = useState(false);

  // Selected job inspection, scoring, tailoring, and export state
  const [selectedResumeId, setSelectedResumeId] = useState<number | null>(null);
  const [scoreReport, setScoreReport] = useState<ATSReport | null>(null);
  const [tailorPreview, setTailorPreview] = useState<TailorPreviewResponse | null>(null);
  const [editedResume, setEditedResume] = useState<CanonicalResume | null>(null);
  const [adaptLocation, setAdaptLocation] = useState(true);
  const [exportResult, setExportResult] = useState<ExportResponse | null>(null);
  const [showRawJd, setShowRawJd] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    if (config?.values.posted_within_default) {
      setFreshness(config.values.posted_within_default);
    }
  }, [config?.values.posted_within_default]);

  const activeSession = useMemo(
    () => sessions.find((s) => s.id === activeSessionId) || null,
    [sessions, activeSessionId]
  );

  const loadJobs = async (sessId: number | null) => {
    try {
      const list = await api.listJobs(sessId);
      setJobs(list);
      setSelectedJobId((prev) =>
        prev && list.some((j) => j.id === prev) ? prev : list[0]?.id ?? null
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session jobs.");
    }
  };

  useEffect(() => {
    setLocationFilter("all");
    setRoleFilter("all");
    setBatchResult(null);
    void loadJobs(activeSessionId);
  }, [activeSessionId]);

  const filteredJobs = useMemo(() => {
    return jobs.filter((j) => {
      if (locationFilter !== "all" && (j.analysis.location || "Unspecified") !== locationFilter) {
        return false;
      }
      if (roleFilter !== "all" && j.analysis.role_track !== roleFilter) {
        return false;
      }
      return true;
    });
  }, [jobs, locationFilter, roleFilter]);

  const selectedJob = useMemo(
    () => filteredJobs.find((j) => j.id === selectedJobId) || filteredJobs[0] || null,
    [filteredJobs, selectedJobId]
  );

  const resumes = resumeState?.resumes ?? [];

  // Auto-select matching role base resume & run score/preview cleanly when job switches
  useEffect(() => {
    if (!selectedJob) {
      setScoreReport(null);
      setTailorPreview(null);
      setEditedResume(null);
      setExportResult(null);
      return;
    }

    const preferredByRole = resumes.find(
      (r) => r.is_base && r.role_track === selectedJob.analysis.role_track
    );
    const anyBase = resumes.find((r) => r.is_base);
    const defaultResId = preferredByRole?.id ?? anyBase?.id ?? resumes[0]?.id ?? null;
    setSelectedResumeId(defaultResId);
    setExportResult(null);
    setTailorPreview(null);
    setEditedResume(null);

    if (defaultResId != null) {
      void (async () => {
        try {
          const [rep, prev] = await Promise.all([
            api.scoreJob(selectedJob.id, defaultResId),
            api.previewTailor(selectedJob.id, defaultResId, adaptLocation),
          ]);
          setScoreReport(rep);
          setTailorPreview(prev);
          setEditedResume(JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume);
        } catch {
          setScoreReport(null);
        }
      })();
    } else {
      setScoreReport(null);
    }
  }, [selectedJob?.id, resumes.length]);

  const trackName = (id: string) =>
    roleTracks.find((t) => t.id === id)?.display_name || id;

  const ensureSessionId = async (): Promise<number> => {
    if (activeSessionId != null) return activeSessionId;
    const created = await api.createSession(newSessionName.trim(), freshness);
    await onSessionsChanged(created.id);
    return created.id;
  };

  const handleCreateSession = async () => {
    setError(null);
    setNotice(null);
    try {
      const created = await api.createSession(newSessionName.trim(), freshness);
      setNewSessionName("");
      await onSessionsChanged(created.id);
      setNotice(`Created ${created.name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create session.");
    }
  };

  const handleBatchScrape = async () => {
    setScraping(true);
    setError(null);
    setNotice(null);
    try {
      const targetSessionId = await ensureSessionId();
      const res = await api.scrapeSessionBatch(targetSessionId, {
        posted_within: freshness,
      });
      setBatchResult(res);
      await Promise.all([onSessionsChanged(targetSessionId), loadJobs(targetSessionId)]);
      setNotice(
        `Scanned ${res.scanned_count} postings (${res.posted_within}): kept ${res.saved_count}, dropped ${res.filtered_count} inline, skipped ${res.duplicate_skipped_count} already seen/discarded.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Batch scrape failed.");
    } finally {
      setScraping(false);
    }
  };

  const handleManualIngest = async () => {
    if (!manualUrl.trim() && !manualText.trim()) {
      setError("Enter a posting URL or paste a job description.");
      return;
    }
    setIngesting(true);
    setError(null);
    setNotice(null);
    try {
      const targetSessionId = await ensureSessionId();
      const created = await api.ingestJob({
        session_id: targetSessionId,
        url: manualUrl.trim() || undefined,
        raw_text: manualText.trim() || undefined,
        company_override: manualCompany.trim() || undefined,
        title_override: manualTitle.trim() || undefined,
        location_override: manualLocation.trim() || undefined,
      });
      setManualUrl("");
      setManualText("");
      setManualCompany("");
      setManualTitle("");
      setManualLocation("");
      setShowManualDrawer(false);
      await Promise.all([onSessionsChanged(targetSessionId), loadJobs(targetSessionId)]);
      setSelectedJobId(created.id);
      setNotice(`Added ${created.analysis.title} at ${created.analysis.company}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add job posting.");
    } finally {
      setIngesting(false);
    }
  };

  const handleDiscardJob = async (jobId: number) => {
    setError(null);
    try {
      await api.patchJob(jobId, { disposition: "discarded" });
      await Promise.all([loadJobs(activeSessionId), onSessionsChanged(activeSessionId ?? undefined)]);
      setNotice("Job discarded permanently and won't be pulled in future sessions.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to discard job.");
    }
  };

  const handleStatusChange = async (jobId: number, status: ApplicationStatus) => {
    setError(null);
    try {
      const updated = await api.patchJob(jobId, { application_status: status });
      setJobs((prev) => prev.map((j) => (j.id === jobId ? updated : j)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update status.");
    }
  };

  const handleResumeSwitch = async (resumeId: number) => {
    if (!selectedJob) return;
    setSelectedResumeId(resumeId);
    setActionBusy(true);
    setError(null);
    try {
      const [rep, prev] = await Promise.all([
        api.scoreJob(selectedJob.id, resumeId),
        api.previewTailor(selectedJob.id, resumeId, adaptLocation),
      ]);
      setScoreReport(rep);
      setTailorPreview(prev);
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
      const prev = await api.previewTailor(selectedJob.id, selectedResumeId, nextVal);
      setTailorPreview(prev);
      setEditedResume(JSON.parse(JSON.stringify(prev.tailored_resume)) as CanonicalResume);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refresh preview.");
    } finally {
      setActionBusy(false);
    }
  };

  const updateTailoredBullet = (expIdx: number, bulletIdx: number, newText: string) => {
    if (!editedResume) return;
    const next = JSON.parse(JSON.stringify(editedResume)) as CanonicalResume;
    if (next.experience[expIdx]?.bullets[bulletIdx]) {
      next.experience[expIdx].bullets[bulletIdx].text = newText;
      setEditedResume(next);
    }
  };

  const handleCreateResume = async () => {
    if (!selectedJob || selectedResumeId == null) {
      setError("Add or select a base resume in the Resume tab first.");
      return;
    }
    setActionBusy(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.exportResume(
        selectedJob.id,
        selectedResumeId,
        editedResume ?? undefined
      );
      setExportResult(res);
      await loadJobs(activeSessionId);
      setNotice(`Created ${res.generated_files.filter((f) => f.endsWith(".pdf") || f.endsWith(".docx")).join(", ")} cleanly.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export resume.");
    } finally {
      setActionBusy(false);
    }
  };

  return (
    <div className="stack-md">
      {/* Top Scrape Session Toolbar */}
      <div className="card stack-md">
        <div className="row-between">
          <div className="row-wrap" style={{ flex: 1 }}>
            <div style={{ minWidth: 220 }}>
              <label>Active Session</label>
              <select
                value={activeSessionId ?? ""}
                onChange={(e) => onSelectSession(Number(e.target.value))}
              >
                {sessions.length === 0 && <option value="">No sessions yet</option>}
                {sessions.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name} ({s.total_jobs} jobs)
                  </option>
                ))}
              </select>
            </div>

            <div style={{ minWidth: 190 }}>
              <label>Posted Within</label>
              <select value={freshness} onChange={(e) => setFreshness(e.target.value)}>
                {FRESHNESS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div style={{ minWidth: 180 }}>
              <label>New Session Name (optional)</label>
              <input
                value={newSessionName}
                onChange={(e) => setNewSessionName(e.target.value)}
                placeholder="e.g. Morning Senior Run"
              />
            </div>

            <div style={{ display: "flex", alignItems: "flex-end", paddingTop: 18, gap: 8 }}>
              <button className="btn" onClick={() => void handleCreateSession()}>
                + New Session
              </button>
              <button
                className="btn btn-primary"
                onClick={() => void handleBatchScrape()}
                disabled={scraping}
              >
                {scraping ? "Scraping & Filtering..." : "Scrape Target Roles"}
              </button>
              <button
                className="btn"
                onClick={() => setShowManualDrawer((v) => !v)}
              >
                {showManualDrawer ? "Close Add URL/JD" : "+ Add URL / Paste JD"}
              </button>
            </div>
          </div>
        </div>

        {/* Configured pull scope hint */}
        {config && (
          <div className="row-wrap small-note">
            <span>
              Roles:{" "}
              <strong>
                {config.values.target_role_tracks.map(trackName).join(", ") || "All"}
              </strong>
            </span>
            <span>&middot;</span>
            <span>
              Auth: <strong>{config.values.work_authorization.toUpperCase()}</strong>
            </span>
            <span>&middot;</span>
            <span>
              Locations: <strong>{config.values.target_locations.join(", ") || "Any"}</strong>
            </span>
            <span>&middot;</span>
            <span className="pill">Omitted salary kept</span>
          </div>
        )}

        {/* Session city & role filter chips */}
        {activeSession && activeSession.total_jobs > 0 && (
          <div className="row-wrap" style={{ paddingTop: 4 }}>
            <button
              className={`chip ${locationFilter === "all" ? "selected" : ""}`}
              onClick={() => setLocationFilter("all")}
            >
              All Cities ({activeSession.total_jobs})
            </button>
            {activeSession.locations.map((loc) => (
              <button
                key={loc.location}
                className={`chip ${locationFilter === loc.location ? "selected" : ""}`}
                onClick={() => setLocationFilter(loc.location)}
              >
                {loc.location} ({loc.count})
              </button>
            ))}
            <span style={{ width: 1, height: 18, background: "var(--border-subtle)" }} />
            <button
              className={`chip ${roleFilter === "all" ? "selected" : ""}`}
              onClick={() => setRoleFilter("all")}
            >
              All Roles
            </button>
            {activeSession.roles.map((r) => (
              <button
                key={r.role_track}
                className={`chip ${roleFilter === r.role_track ? "selected" : ""}`}
                onClick={() => setRoleFilter(r.role_track)}
              >
                {trackName(r.role_track)} ({r.count})
              </button>
            ))}
          </div>
        )}
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {/* Inline filter breakdown from latest scrape */}
      {batchResult && (
        <div className="card-elevated stack-sm">
          <div className="row-between">
            <strong>Batch Scrape Inline Filter Summary ({batchResult.posted_within})</strong>
            <div className="row-wrap">
              <span className="pill">Scanned: {batchResult.scanned_count}</span>
              <span className="pill pill-green">Saved: {batchResult.saved_count}</span>
              <span className="pill pill-amber">Filtered: {batchResult.filtered_count}</span>
              <span className="pill">Seen/Discarded Skipped: {batchResult.duplicate_skipped_count}</span>
            </div>
          </div>
          {Object.keys(batchResult.filter_breakdown).length > 0 && (
            <div className="row-wrap">
              {Object.entries(batchResult.filter_breakdown).map(([reason, count]) => (
                <span key={reason} className="pill">
                  {reason}: {count}
                </span>
              ))}
            </div>
          )}
          {batchResult.source_notes.length > 0 && (
            <div className="small-note">
              Source notes: {batchResult.source_notes.slice(0, 3).join(" | ")}
            </div>
          )}
        </div>
      )}

      {/* Manual URL / Paste JD Drawer */}
      {showManualDrawer && (
        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Add Single Job Posting by URL or Text</h3>
          <div className="form-grid-2">
            <div>
              <label>Job URL (optional if pasting JD below)</label>
              <input
                value={manualUrl}
                onChange={(e) => setManualUrl(e.target.value)}
                placeholder="https://boards.greenhouse.io/..."
              />
            </div>
            <div className="form-grid-3">
              <div>
                <label>Company Override</label>
                <input
                  value={manualCompany}
                  onChange={(e) => setManualCompany(e.target.value)}
                  placeholder="Optional"
                />
              </div>
              <div>
                <label>Title Override</label>
                <input
                  value={manualTitle}
                  onChange={(e) => setManualTitle(e.target.value)}
                  placeholder="Optional"
                />
              </div>
              <div>
                <label>Location Override</label>
                <input
                  value={manualLocation}
                  onChange={(e) => setManualLocation(e.target.value)}
                  placeholder="Seattle, WA"
                />
              </div>
            </div>
          </div>
          <div>
            <label>Pasted Job Description</label>
            <textarea
              rows={5}
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              placeholder="Paste the full job description text here if behind login/anti-bot wall..."
            />
          </div>
          <div className="row-between">
            <span className="small-note">Role track is automatically inferred from title & keywords.</span>
            <button
              className="btn btn-primary"
              onClick={() => void handleManualIngest()}
              disabled={ingesting}
            >
              {ingesting ? "Analyzing..." : "Analyze & Add to Session"}
            </button>
          </div>
        </div>
      )}

      {/* Master-Detail Session Postings Workspace */}
      {filteredJobs.length === 0 ? (
        <div className="card stack-sm" style={{ textAlign: "center", padding: 36 }}>
          <h3 style={{ margin: 0 }}>No Jobs in This Session Yet</h3>
          <p className="muted" style={{ margin: 0 }}>
            Click <strong>Scrape Target Roles</strong> above or add a single URL/JD.
          </p>
        </div>
      ) : (
        <div className="master-detail-grid">
          {/* Left Job List */}
          <div className="job-list">
            {filteredJobs.map((job) => {
              const isSelected = selectedJob?.id === job.id;
              return (
                <div
                  key={job.id}
                  className={`job-item ${isSelected ? "selected" : ""}`}
                  onClick={() => setSelectedJobId(job.id)}
                >
                  <div className="stack-sm">
                    <div className="row-between">
                      <h4 className="job-title">{job.analysis.title}</h4>
                      <span className="pill pill-blue mono">
                        {Math.round(job.relevance_score)}%
                      </span>
                    </div>
                    <div className="job-company">
                      {job.analysis.company} &middot; {job.analysis.location || "Unspecified"}
                    </div>
                    <div className="row-wrap">
                      <span className="pill">{trackName(job.analysis.role_track)}</span>
                      <span className={job.analysis.salary.min_amount == null ? "pill" : "pill pill-green"}>
                        {formatCompensation(job)}
                      </span>
                      <span className={STATUS_BADGE_CLASS[job.application_status]}>
                        {job.application_status.replace("_", " ")}
                      </span>
                    </div>
                    <div className="row-between" onClick={(e) => e.stopPropagation()}>
                      <span className="small-note">
                        {job.work_type !== "unspecified" ? job.work_type : job.job_type}
                        {job.work_auth === "h1b_ok" ? " · H1B" : ""}
                      </span>
                      <button
                        className="btn btn-sm btn-danger-ghost"
                        onClick={() => void handleDiscardJob(job.id)}
                      >
                        Discard
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Right Detail Inspection, Resumes in Hand, Skills Gap & Create Resume */}
          {selectedJob && (
            <div className="card stack-md">
              <div className="row-between">
                <div>
                  <h2 style={{ margin: 0, fontSize: 20 }}>{selectedJob.analysis.title}</h2>
                  <div className="muted" style={{ marginTop: 2 }}>
                    <strong>{selectedJob.analysis.company}</strong> &middot;{" "}
                    {selectedJob.analysis.location || "Unspecified Location"} &middot; Source:{" "}
                    {selectedJob.source}
                  </div>
                </div>
                <div className="row-wrap">
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
                    <option value="skipped">Status: Skipped</option>
                  </select>
                  <button
                    className="btn btn-danger-ghost"
                    onClick={() => void handleDiscardJob(selectedJob.id)}
                  >
                    Discard
                  </button>
                </div>
              </div>

              <div className="row-wrap">
                <span className="pill pill-blue">{trackName(selectedJob.analysis.role_track)}</span>
                <span className="pill">{formatCompensation(selectedJob)}</span>
                <span className="pill">
                  YoE:{" "}
                  {selectedJob.analysis.yoe.min_years != null
                    ? `${selectedJob.analysis.yoe.min_years}+ yrs`
                    : "Not specified"}
                </span>
                <span className="pill">{selectedJob.work_type}</span>
                <span className="pill">{selectedJob.job_type}</span>
                <span className="pill">
                  Auth: {selectedJob.work_auth === "h1b_ok" ? "H-1B Mentioned" : selectedJob.work_auth}
                </span>
                {selectedJob.url && (
                  <a
                    className="pill"
                    href={selectedJob.url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open Original Posting
                  </a>
                )}
              </div>

              {/* Resumes in Hand Selector */}
              <div className="card-elevated stack-sm">
                <div className="row-between">
                  <strong>Resumes in Hand (click to evaluate & tailor)</strong>
                  <button
                    className="btn btn-sm"
                    onClick={() => onNavigateTab("resume")}
                  >
                    Manage Resumes
                  </button>
                </div>

                {resumes.length === 0 ? (
                  <div className="row-between alert alert-info">
                    <span>No base resumes created or uploaded yet.</span>
                    <button
                      className="btn btn-sm btn-primary"
                      onClick={() => onNavigateTab("resume")}
                    >
                      Create / Upload Base Resume
                    </button>
                  </div>
                ) : (
                  <div className="row-wrap">
                    {resumes.map((r) => {
                      const matchesTrack = r.role_track === selectedJob.analysis.role_track;
                      return (
                        <button
                          key={r.id}
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
              </div>

              {/* ATS Relevance Score & Per-Job Skills Gap */}
              {scoreReport && (
                <div className="card-elevated stack-md">
                  <div className="row-between">
                    <div>
                      <strong style={{ fontSize: 15 }}>ATS Relevance & Skills Gap</strong>
                      <div className="small-note">
                        Estimated length: {scoreReport.estimated_pages} page(s)
                      </div>
                    </div>
                    <div className="row-wrap">
                      <span className="pill pill-blue" style={{ fontSize: 14, padding: "5px 12px" }}>
                        Match Score: {scoreReport.overall_score}%
                      </span>
                      {tailorPreview && tailorPreview.tailored_score > tailorPreview.base_score && (
                        <span className="pill pill-green" style={{ fontSize: 14, padding: "5px 12px" }}>
                          After Tailoring: {tailorPreview.tailored_score}%
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="form-grid-2">
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        Matched Skills ({scoreReport.matched_skills.length})
                      </div>
                      <div className="row-wrap">
                        {scoreReport.matched_skills.map((s) => (
                          <span key={s.keyword} className="pill pill-green">
                            {s.keyword}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        Missing Skills Gap ({scoreReport.missing_skills.length})
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
                </div>
              )}

              {/* Before / After Tailoring Preview & Create Resume Action */}
              {tailorPreview && editedResume && (
                <div className="card-elevated stack-md">
                  <div className="row-between">
                    <div>
                      <strong style={{ fontSize: 15 }}>
                        Before / After Tailoring
                      </strong>
                      <div className="small-note">
                        Edit tailored bullets or match city header before exporting.
                      </div>
                    </div>
                    <div className="row-wrap">
                      <label className="row-wrap" style={{ margin: 0, cursor: "pointer" }}>
                        <input
                          type="checkbox"
                          style={{ width: "auto" }}
                          checked={adaptLocation}
                          onChange={(e) => void handleToggleAdaptLocation(e.target.checked)}
                        />
                        Match Resume Location to {selectedJob.analysis.location || "Job"}
                      </label>
                      <button
                        className="btn btn-primary"
                        onClick={() => void handleCreateResume()}
                        disabled={actionBusy}
                      >
                        {actionBusy ? "Creating..." : "Create Resume"}
                      </button>
                    </div>
                  </div>

                  {tailorPreview.field_changes.length > 0 && (
                    <div className="stack-sm">
                      {tailorPreview.field_changes.map((fc, idx) => (
                        <div key={idx} className="alert alert-info">
                          <strong>{fc.field_name}:</strong>{" "}
                          <span className="muted">{fc.before}</span> &rarr;{" "}
                          <strong>{fc.after}</strong> ({fc.reason})
                        </div>
                      ))}
                    </div>
                  )}

                  {tailorPreview.experience_comparisons.map((exp, expIdx) => (
                    <div key={exp.experience_id || expIdx} className="card stack-sm">
                      <div className="row-between">
                        <strong>
                          {exp.title} @ {exp.company}
                        </strong>
                        <span className="small-note">{exp.dates}</span>
                      </div>
                      {exp.bullets.map((b, bIdx) => (
                        <div key={b.bullet_id || bIdx} className="diff-grid">
                          <div className="diff-box">
                            <div className="small-note" style={{ marginBottom: 4 }}>
                              Original ({b.status})
                            </div>
                            <div>{b.original_text}</div>
                          </div>
                          <div className="diff-box">
                            <div className="small-note" style={{ marginBottom: 4 }}>
                              Tailored (Editable)
                            </div>
                            <textarea
                              rows={2}
                              value={
                                editedResume.experience[expIdx]?.bullets[bIdx]?.text ??
                                b.tailored_text
                              }
                              onChange={(e) =>
                                updateTailoredBullet(expIdx, bIdx, e.target.value)
                              }
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              )}

              {/* Export Download Links */}
              {exportResult && (
                <div className="alert alert-success stack-sm">
                  <div className="row-between">
                    <strong>
                      Resume Created Locally in folder: <span className="mono">{exportResult.folder_name}</span>
                    </strong>
                    <span className="pill pill-green">Final Score: {exportResult.ats_score}%</span>
                  </div>
                  <div className="row-wrap">
                    {exportResult.generated_files.map((fname) => (
                      <a
                        key={fname}
                        className="btn btn-sm btn-success"
                        href={api.downloadArtifactUrl(exportResult.run_id, fname)}
                        download={fname}
                      >
                        Download {fname}
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Expandable Full JD */}
              <div>
                <button
                  className="btn btn-sm"
                  onClick={() => setShowRawJd((v) => !v)}
                >
                  {showRawJd ? "Hide Full Job Description" : "Show Full Job Description"}
                </button>
                {showRawJd && (
                  <pre className="pre-box" style={{ marginTop: 10 }}>
                    {selectedJob.raw_text}
                  </pre>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
