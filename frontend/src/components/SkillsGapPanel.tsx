import { useEffect, useState } from "react";
import { api } from "../api";
import type { RoleTrackConfig, ScrapeSessionSummary, SessionSkillsGapResponse, TabId } from "../types";

interface SkillsGapPanelProps {
  sessions: ScrapeSessionSummary[];
  activeSessionId: number | null;
  roleTracks: RoleTrackConfig[];
  onNavigateTab: (tab: TabId) => void;
}

export function SkillsGapPanel({
  sessions,
  activeSessionId,
  roleTracks,
  onNavigateTab,
}: SkillsGapPanelProps) {
  const [scopeSessionId, setScopeSessionId] = useState<number | null>(activeSessionId);
  const [data, setData] = useState<SessionSkillsGapResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setScopeSessionId(activeSessionId);
  }, [activeSessionId]);

  const loadGap = async (targetSessionId: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.getSkillsGap(targetSessionId);
      setData(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load skills gap report.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadGap(scopeSessionId);
  }, [scopeSessionId]);

  const trackLabel = (id: string) =>
    roleTracks.find((t) => t.id === id)?.display_name || id;

  return (
    <div className="stack-lg">
      <div className="card row-between">
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Skills Gap</h2>
          <div className="muted">
            JD skill demand compared against your base resumes.
          </div>
        </div>
        <div className="row-wrap">
          <div style={{ minWidth: 230 }}>
            <select
              value={scopeSessionId ?? ""}
              onChange={(e) =>
                setScopeSessionId(e.target.value ? Number(e.target.value) : null)
              }
            >
              <option value="">All Sessions</option>
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.total_jobs} jobs)
                </option>
              ))}
            </select>
          </div>
          <button
            className="btn"
            onClick={() => void loadGap(scopeSessionId)}
            disabled={loading}
          >
            {loading ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}

      {data && (
        <>
          <div className="kpi-grid">
            <div className="kpi-card">
              <div className="kpi-label">Active Jobs Analyzed</div>
              <div className="kpi-value">{data.total_active_jobs}</div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Skills Covered in Resumes</div>
              <div className="kpi-value" style={{ color: "var(--accent-green)" }}>
                {data.covered_skill_count}
              </div>
            </div>
            <div className="kpi-card">
              <div className="kpi-label">Missing High-Demand Skills</div>
              <div className="kpi-value" style={{ color: "var(--accent-amber)" }}>
                {data.missing_skill_count}
              </div>
            </div>
          </div>

          <div className="report-grid">
            <div className="card">
              <div className="row-between" style={{ marginBottom: 12 }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>Top Missing Skills (Opportunity Areas)</h3>
                <span className="pill pill-amber">{data.overall_missing.length} shown</span>
              </div>
              {data.overall_missing.length === 0 ? (
                <p className="muted">
                  {data.total_active_jobs === 0
                    ? "Scrape or ingest jobs in Sessions first to see skill gaps."
                    : "Your base resumes cover all tracked JD skills in this session."}
                </p>
              ) : (
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Skill</th>
                      <th>Priority</th>
                      <th>JD Demand</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.overall_missing.map((item) => (
                      <tr key={item.keyword}>
                        <td>
                          <strong>{item.keyword}</strong>
                        </td>
                        <td>
                          <span className="pill pill-blue">{item.priority_label}</span>
                        </td>
                        <td className="mono">
                          {item.demand_count} jobs ({item.demand_pct}%)
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>

            <div className="card">
              <div className="row-between" style={{ marginBottom: 12 }}>
                <h3 style={{ margin: 0, fontSize: 15 }}>Covered Strengths Across Resumes</h3>
                <span className="pill pill-green">{data.overall_strengths.length} matched</span>
              </div>
              {data.overall_strengths.length === 0 ? (
                <p className="muted">
                  Add a base resume in the Resume tab to map strengths against incoming jobs.
                </p>
              ) : (
                <div className="stack-sm">
                  {data.overall_strengths.map((item) => (
                    <div key={item.keyword} className="card-elevated row-between">
                      <div>
                        <strong>{item.keyword}</strong>{" "}
                        <span className="small-note">({item.priority_label})</span>
                        <div className="small-note">
                          Covered in: {item.covered_by_resumes.join(", ")}
                        </div>
                      </div>
                      <span className="pill pill-green mono">
                        {item.demand_count} ({item.demand_pct}%)
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {data.by_role.length > 0 && (
            <div className="card">
              <h3 style={{ margin: "0 0 14px", fontSize: 15 }}>Gap Breakdown by Target Role</h3>
              <div className="report-grid">
                {data.by_role.map((role) => (
                  <div key={role.role_track} className="card-elevated stack-sm">
                    <div className="row-between">
                      <strong>{trackLabel(role.role_track)}</strong>
                      <div className="row-wrap">
                        <span className="pill">{role.job_count} jobs</span>
                        <span className="pill pill-blue">Avg {role.avg_relevance}%</span>
                      </div>
                    </div>
                    {!role.has_base_resume && (
                      <div className="row-between alert alert-info">
                        <span>No base resume dedicated to this role track yet.</span>
                        <button
                          className="btn btn-sm btn-primary"
                          onClick={() => onNavigateTab("resume")}
                        >
                          Add Resume
                        </button>
                      </div>
                    )}
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        Missing Skills
                      </div>
                      <div className="row-wrap">
                        {role.top_missing_skills.length === 0 ? (
                          <span className="pill pill-green">None missing</span>
                        ) : (
                          role.top_missing_skills.map((sk) => (
                            <span key={sk.keyword} className="pill pill-amber">
                              {sk.keyword} ({sk.demand_pct}%)
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="small-note" style={{ marginBottom: 6 }}>
                        Matched Strengths
                      </div>
                      <div className="row-wrap">
                        {role.top_matched_skills.length === 0 ? (
                          <span className="muted">No resume matches yet</span>
                        ) : (
                          role.top_matched_skills.map((sk) => (
                            <span key={sk.keyword} className="pill pill-green">
                              {sk.keyword} ({sk.demand_pct}%)
                            </span>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
