import { useEffect, useState } from "react";
import { api } from "../api";
import { formatEasternDateTime } from "../utils/datetime";
import { formatSkillName } from "../constants/tailoring";
import type {
  AnalyticsReportResponse,
  ApplicationStatus,
  AppliedJobSummaryItem,
  ReportBucketItem,
  ScrapeSessionSummary,
} from "../types";

interface ReportsPanelProps {
  sessions: ScrapeSessionSummary[];
  activeSessionId: number | null;
  onJobsUpdated?: () => Promise<void>;
}

const APPLIED_STANDING_OPTIONS: { value: ApplicationStatus; label: string }[] = [
  { value: "applied", label: "Applied" },
  { value: "screening", label: "Screening" },
  { value: "interviewing", label: "Interviewing" },
  { value: "offer", label: "Offer Received" },
  { value: "rejected", label: "Rejected" },
  { value: "resume_created", label: "Resume Created" },
];

const STANDING_PILL_CLASS: Record<string, string> = {
  applied: "pill pill-blue",
  screening: "pill pill-blue",
  interviewing: "pill pill-green",
  offer: "pill pill-green",
  rejected: "pill pill-red",
  resume_created: "pill",
};

function MetricBarCard({
  title,
  items,
  accent,
}: {
  title: string;
  items: ReportBucketItem[];
  accent: string;
}) {
  const maxVal = items.length > 0 ? Math.max(...items.map((i) => i.count)) || 1 : 1;
  return (
    <div className="card">
      <h3 style={{ margin: "0 0 14px", fontSize: 14, textTransform: "uppercase", letterSpacing: "0.04em", color: "var(--text-secondary)" }}>
        {title}
      </h3>
      {items.length === 0 ? (
        <p className="muted">No data recorded yet.</p>
      ) : (
        <div className="bar-chart">
          {items.map((item) => {
            const width = Math.max(4, Math.round((item.count / maxVal) * 100));
            return (
              <div key={item.label}>
                <div className="bar-row-meta">
                  <span>
                    {item.label
                      .replace(/^seen:saved$/i, "Seen: Saved")
                      .replace(/^seen:auto[_\s-]?filtered$/i, "Seen: Auto-Filtered")
                      .replace(/^seen:discarded$/i, "Seen: Discarded")
                      .replace(/^seen:skipped$/i, "Seen: Skipped")}
                  </span>
                  <span className="mono muted">
                    {item.count} ({item.pct}%)
                  </span>
                </div>
                <div className="bar-track">
                  <div
                    className="bar-fill"
                    style={{ width: `${width}%`, background: accent }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function ReportsPanel({ sessions, activeSessionId, onJobsUpdated }: ReportsPanelProps) {
  const [scopeSessionId, setScopeSessionId] = useState<number | null>(activeSessionId);
  const [report, setReport] = useState<AnalyticsReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [savingJobId, setSavingJobId] = useState<number | null>(null);
  const [notesDraftByJob, setNotesDraftByJob] = useState<Record<number, string>>({});

  useEffect(() => {
    setScopeSessionId(activeSessionId);
  }, [activeSessionId]);

  const loadReports = async (targetSessionId: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getReports(targetSessionId);
      setReport(res);
      const nextNotes: Record<number, string> = {};
      for (const item of res.applied_jobs ?? []) {
        nextNotes[item.job_id] = item.application_notes ?? "";
      }
      setNotesDraftByJob(nextNotes);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics report.");
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateStanding = async (
    item: AppliedJobSummaryItem,
    nextStatus?: ApplicationStatus,
    nextNotes?: string
  ) => {
    setSavingJobId(item.job_id);
    setError(null);
    try {
      await api.patchJob(item.job_id, {
        ...(nextStatus !== undefined ? { application_status: nextStatus } : {}),
        ...(nextNotes !== undefined ? { application_notes: nextNotes } : {}),
      });
      await loadReports(scopeSessionId);
      if (onJobsUpdated) {
        await onJobsUpdated();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update application standing.");
    } finally {
      setSavingJobId(null);
    }
  };

  useEffect(() => {
    void loadReports(scopeSessionId);
  }, [scopeSessionId]);

  return (
    <div className="stack-lg">
      <div className="card row-between">
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Reports &amp; Standing</h2>
          <div className="muted">
            Funnel metrics, company &amp; domain insights, live applied-jobs standing, HTML dashboard &amp; Excel (.xlsx) export.
          </div>
        </div>
        <div className="row-wrap">
          <div style={{ minWidth: 220 }}>
            <select
              value={scopeSessionId ?? ""}
              onChange={(e) =>
                setScopeSessionId(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">All Sessions</option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.total_jobs} active)
                </option>
              ))}
            </select>
          </div>
          <button
            className="btn"
            onClick={() => void loadReports(scopeSessionId)}
            disabled={loading}
          >
            {loading ? "Updating..." : "Refresh"}
          </button>
          <a
            className="btn"
            href={api.excelReportUrl(scopeSessionId)}
            download
          >
            Export Excel (.xlsx)
          </a>
          <a
            className="btn btn-primary"
            href={api.htmlReportUrl(scopeSessionId)}
            target="_blank"
            rel="noreferrer"
          >
            Open Standalone HTML Report
          </a>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {report && (
        <>
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Total Scanned</div>
              <div className="kpi-value">{report.total_scanned}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Saved Active Jobs</div>
              <div className="kpi-value" style={{ color: "var(--accent-green)" }}>
                {report.total_saved}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Applied / Active Pipeline</div>
              <div className="kpi-value" style={{ color: "var(--accent-blue)" }}>
                {report.total_applied ?? 0}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Interviews / Offers</div>
              <div className="kpi-value" style={{ color: "var(--accent-green)" }}>
                {report.interviewing_count ?? 0} / {report.offer_count ?? 0}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Avg Base &rarr; Tailored ATS</div>
              <div className="kpi-value" style={{ color: "var(--accent-blue)" }}>
                {report.avg_relevance_score}% &rarr; {report.avg_tailored_score ?? 0}%
                {(report.avg_ats_lift ?? 0) > 0 && (
                  <span style={{ fontSize: 13, color: "var(--accent-green)", marginLeft: 6 }}>
                    (+{report.avg_ats_lift}%)
                  </span>
                )}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Exports / Filtered / Discarded</div>
              <div className="kpi-value" style={{ color: "var(--accent-amber)", fontSize: 20 }}>
                {report.total_exports} &middot; {report.total_filtered} &middot; {report.total_discarded}
              </div>
            </div>
          </div>

          <div className="row-between small-note" style={{ padding: "0 4px" }}>
            <span>
              Seen Ledger: <strong>{report.seen_ledger_count}</strong> jobs tracked (skips saved &amp; discarded)
              {" · "}Kept without salary: <strong>{report.omitted_salary_count}</strong>
              {" · "}Generated <strong>{formatEasternDateTime(report.generated_at)}</strong>
            </span>
          </div>

          {/* Dedicated Applied Jobs & Current Standing Tracker */}
          <div className="card stack-md">
            <div className="row-between">
              <div>
                <h3 style={{ margin: 0, fontSize: 16 }}>
                  Jobs Applied &amp; Current Standing ({(report.applied_jobs ?? []).length})
                </h3>
                <div className="small-note">
                  Shows every role marked Applied, Screening, Interviewing, Offer, or Rejected — update your pipeline stage or notes directly below.
                </div>
              </div>
            </div>

            {!report.applied_jobs || report.applied_jobs.length === 0 ? (
              <div className="alert alert-info">
                No jobs are marked as <strong>Applied</strong> yet. Mark a job as Applied in the{" "}
                <strong>Sessions</strong> workspace to track interviews, offers, and notes here.
              </div>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Company &amp; Role</th>
                      <th>Session &amp; Track</th>
                      <th>Applied Date</th>
                      <th>Base &rarr; Tailored</th>
                      <th>Standing</th>
                      <th>Application Notes</th>
                      <th>Files</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.applied_jobs.map((item) => {
                      const draftNote = notesDraftByJob[item.job_id] ?? item.application_notes ?? "";
                      const notesDirty = draftNote !== (item.application_notes ?? "");
                      return (
                        <tr key={item.job_id}>
                          <td>
                            <div>
                              <strong>{item.company}</strong> — {item.title}
                            </div>
                            <div className="small-note">
                              {item.location}
                              {item.url && (
                                <>
                                  {" · "}
                                  <a href={item.url} target="_blank" rel="noreferrer">
                                    Posting &nearr;
                                  </a>
                                </>
                              )}
                            </div>
                          </td>
                          <td>
                            <div style={{ fontSize: 12.5 }}>{item.session_name}</div>
                            <span className="pill">{item.role_label}</span>
                          </td>
                          <td className="mono" style={{ fontSize: 12 }}>
                            {formatEasternDateTime(item.applied_at)}
                          </td>
                          <td className="mono" style={{ fontSize: 12 }}>
                            {item.base_score ?? 0}% &rarr;{" "}
                            <strong style={{ color: "var(--accent-green)" }}>
                              {item.tailored_score != null ? `${item.tailored_score}%` : "—"}
                            </strong>
                          </td>
                          <td>
                            <select
                              style={{ width: 148, padding: "5px 8px" }}
                              value={item.application_status}
                              disabled={savingJobId === item.job_id}
                              onChange={(e) =>
                                void handleUpdateStanding(item, e.target.value as ApplicationStatus)
                              }
                            >
                              {APPLIED_STANDING_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                  {opt.label}
                                </option>
                              ))}
                            </select>
                            <div style={{ marginTop: 4 }}>
                              <span className={STANDING_PILL_CLASS[item.application_status] || "pill"}>
                                {item.status_label}
                              </span>
                            </div>
                          </td>
                          <td style={{ minWidth: 220 }}>
                            <div className="row-wrap" style={{ flexWrap: "nowrap", gap: 6 }}>
                              <input
                                value={draftNote}
                                onChange={(e) =>
                                  setNotesDraftByJob((prev) => ({
                                    ...prev,
                                    [item.job_id]: e.target.value,
                                  }))
                                }
                                placeholder="Recruiter screen, round 1 date..."
                                style={{ fontSize: 12.5, padding: "5px 8px" }}
                              />
                              {notesDirty && (
                                <button
                                  type="button"
                                  className="btn btn-sm btn-primary"
                                  disabled={savingJobId === item.job_id}
                                  onClick={() => void handleUpdateStanding(item, undefined, draftNote)}
                                >
                                  Save
                                </button>
                              )}
                            </div>
                          </td>
                          <td>
                            {item.latest_run_id && item.latest_files.length > 0 ? (
                              <div className="row-wrap" style={{ gap: 4 }}>
                                {item.latest_files.map((fname) => (
                                  <a
                                    key={fname}
                                    className="btn btn-sm"
                                    href={api.downloadArtifactUrl(item.latest_run_id!, fname)}
                                  >
                                    {fname.endsWith(".pdf") ? "PDF" : "DOCX"}
                                  </a>
                                ))}
                              </div>
                            ) : (
                              <span className="small-note">—</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="report-grid">
            <MetricBarCard
              title="Top Companies (Open Roles)"
              items={report.by_company ?? []}
              accent="#0a84ff"
            />
            <MetricBarCard
              title="Engineering Domains"
              items={report.by_domain ?? []}
              accent="#5e5ce6"
            />
            <MetricBarCard
              title="Pipeline Conversion Funnel"
              items={report.funnel_stages ?? []}
              accent="#30d158"
            />
            <MetricBarCard
              title="Posted Freshness Window"
              items={report.by_posted_freshness ?? []}
              accent="#64d2ff"
            />
            <MetricBarCard title="Jobs by Location" items={report.by_location} accent="#0a84ff" />
            <MetricBarCard title="Jobs by Target Role" items={report.by_role} accent="#30d158" />
            <MetricBarCard title="Application Status" items={report.by_status} accent="#64d2ff" />
            <MetricBarCard title="Inline Filter Drops" items={report.by_filter_reason} accent="#ff9f0a" />
            <MetricBarCard title="Sources" items={report.by_source} accent="#bf5af2" />
            <MetricBarCard title="Salary Currencies Detected" items={report.by_currency} accent="#32d74b" />
          </div>

          <div className="card stack-sm">
            <div className="row-between">
              <div>
                <h3 style={{ margin: 0, fontSize: 16 }}>Market Skill Gaps</h3>
                <div className="small-note" style={{ marginTop: 2 }}>
                  Identifies competencies demanded across your active saved postings that are missing from your base profile. Adding these will directly boost ATS calibration.
                </div>
              </div>
              <span className="pill pill-amber">{report.top_missing_skills.length} high-impact gaps</span>
            </div>

            {report.top_missing_skills.length === 0 ? (
              <p className="muted">Zero skill gaps recorded — your base profile covers 100% of tracked skills in this scope!</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>High-Impact Skill</th>
                    <th>Market Demand &amp; Signal</th>
                    <th>Est. ATS Match Lift</th>
                    <th>Priority Level</th>
                    <th>Quick Action</th>
                  </tr>
                </thead>
                <tbody>
                  {report.top_missing_skills.map((sk) => {
                    const lift = Math.min(10, Math.max(3, Math.round(sk.demand_pct / 6) + 2));
                    return (
                      <tr key={sk.keyword}>
                        <td>
                          <strong>{formatSkillName(sk.keyword)}</strong>
                        </td>
                        <td>
                          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={{ width: 80, height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
                              <div style={{ width: `${Math.min(100, sk.demand_pct * 1.5)}%`, height: "100%", background: "var(--accent-amber)", borderRadius: 3 }} />
                            </div>
                            <span className="mono" style={{ fontSize: 12 }}>
                              {sk.demand_count} jobs ({sk.demand_pct}%)
                            </span>
                          </div>
                        </td>
                        <td>
                          <span className="pill pill-green">+{lift}% match lift</span>
                        </td>
                        <td>
                          <span className="pill pill-blue">{sk.priority_label}</span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="btn btn-sm"
                            onClick={() => {
                              void navigator.clipboard.writeText(sk.keyword);
                              setNotice(`Copied '${sk.keyword}' to clipboard — paste into Base Resume Skills or Role Track!`);
                              setTimeout(() => setNotice(null), 4000);
                            }}
                          >
                            Copy Skill
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
