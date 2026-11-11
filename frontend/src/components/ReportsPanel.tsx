import { useEffect, useState } from "react";
import { api } from "../api";
import type { AnalyticsReportResponse, ReportBucketItem, ScrapeSessionSummary } from "../types";

interface ReportsPanelProps {
  sessions: ScrapeSessionSummary[];
  activeSessionId: number | null;
}

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
                  <span>{item.label}</span>
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

export function ReportsPanel({ sessions, activeSessionId }: ReportsPanelProps) {
  const [scopeSessionId, setScopeSessionId] = useState<number | null>(activeSessionId);
  const [report, setReport] = useState<AnalyticsReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setScopeSessionId(activeSessionId);
  }, [activeSessionId]);

  const loadReports = async (targetSessionId: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getReports(targetSessionId);
      setReport(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics report.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadReports(scopeSessionId);
  }, [scopeSessionId]);

  return (
    <div className="stack-lg">
      <div className="card row-between">
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Reports</h2>
          <div className="muted">
            Funnel metrics, inline filter drops &amp; HTML export.
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
              <div className="kpi-label">Auto-Filtered Inline</div>
              <div className="kpi-value" style={{ color: "var(--accent-amber)" }}>
                {report.total_filtered}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Manually Discarded</div>
              <div className="kpi-value" style={{ color: "var(--accent-red)" }}>
                {report.total_discarded}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Kept Without Salary</div>
              <div className="kpi-value">{report.omitted_salary_count}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Avg Match / Resumes Created</div>
              <div className="kpi-value" style={{ color: "var(--accent-blue)" }}>
                {report.avg_relevance_score}% / {report.total_exports}
              </div>
            </div>
          </div>

          <div className="row-between small-note" style={{ padding: "0 4px" }}>
            <span>
              Seen Ledger: <strong>{report.seen_ledger_count}</strong> jobs tracked (skips saved &amp; discarded)
            </span>
            {report.html_report_path && (
              <span className="mono">Saved locally: {report.html_report_path}</span>
            )}
          </div>

          <div className="report-grid">
            <MetricBarCard title="Jobs by Location" items={report.by_location} accent="#0a84ff" />
            <MetricBarCard title="Jobs by Target Role" items={report.by_role} accent="#30d158" />
            <MetricBarCard title="Application Status" items={report.by_status} accent="#64d2ff" />
            <MetricBarCard title="Inline Filter Drops" items={report.by_filter_reason} accent="#ff9f0a" />
            <MetricBarCard title="Sources" items={report.by_source} accent="#bf5af2" />
            <MetricBarCard title="Salary Currencies Detected" items={report.by_currency} accent="#32d74b" />
          </div>

          <div className="card">
            <h3 style={{ margin: "0 0 12px", fontSize: 15 }}>Top Missing Skills</h3>
            {report.top_missing_skills.length === 0 ? (
              <p className="muted">No skill gaps recorded for this scope.</p>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Skill</th>
                    <th>Priority</th>
                    <th>Demand</th>
                  </tr>
                </thead>
                <tbody>
                  {report.top_missing_skills.map((sk) => (
                    <tr key={sk.keyword}>
                      <td><strong>{sk.keyword}</strong></td>
                      <td><span className="pill pill-blue">{sk.priority_label}</span></td>
                      <td className="mono">{sk.demand_count} jobs ({sk.demand_pct}%)</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </>
      )}
    </div>
  );
}
