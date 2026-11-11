import { useEffect, useState } from "react";
import { api } from "../api";
import type { AppSettingsValues, ConfigResponse, RoleTrackConfig } from "../types";

interface ConfigPanelProps {
  config: ConfigResponse | null;
  roleTracks: RoleTrackConfig[];
  onUpdated: () => Promise<void>;
}

function parseListInput(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function ConfigPanel({ config, roleTracks, onUpdated }: ConfigPanelProps) {
  const [draft, setDraft] = useState<AppSettingsValues | null>(null);
  const [locInput, setLocInput] = useState("");
  const [boardsInput, setBoardsInput] = useState("");
  const [blocklistInput, setBlocklistInput] = useState("");

  const [selectedTrackId, setSelectedTrackId] = useState("senior_swe");
  const [aliasesText, setAliasesText] = useState("");
  const [coreKwText, setCoreKwText] = useState("");
  const [sysKwText, setSysKwText] = useState("");

  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!config) return;
    setDraft(config.values);
    setLocInput(config.values.target_locations.join(", "));
    setBoardsInput(config.values.company_boards.join("\n"));
    setBlocklistInput(config.values.title_blocklist.join(", "));
  }, [config]);

  useEffect(() => {
    const track = roleTracks.find((t) => t.id === selectedTrackId) || roleTracks[0];
    if (!track) return;
    setSelectedTrackId(track.id);
    setAliasesText(track.aliases.join(", "));
    setCoreKwText((track.keywords.core_must_have || []).join(", "));
    setSysKwText((track.keywords.important_systems || []).join(", "));
  }, [roleTracks, selectedTrackId]);

  if (!config || !draft) {
    return <div className="card muted">Loading configuration...</div>;
  }

  const toggleArrayValue = <T extends string>(arr: T[], val: T): T[] =>
    arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val];

  const handleSaveSettings = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateConfig({
        target_role_tracks: draft.target_role_tracks,
        target_locations: parseListInput(locInput),
        work_types: draft.work_types,
        job_types: draft.job_types,
        work_authorization: draft.work_authorization,
        posted_within_default: draft.posted_within_default,
        target_yoe_min: Number(draft.target_yoe_min),
        target_yoe_max: Number(draft.target_yoe_max),
        target_salary_min:
          draft.target_salary_min === null || Number.isNaN(draft.target_salary_min)
            ? null
            : Number(draft.target_salary_min),
        min_hourly_rate:
          draft.min_hourly_rate === null || Number.isNaN(draft.min_hourly_rate)
            ? null
            : Number(draft.min_hourly_rate),
        min_relevance_score: Number(draft.min_relevance_score || 0),
        scraper_sources: draft.scraper_sources,
        company_boards: parseListInput(boardsInput),
        title_blocklist: parseListInput(blocklistInput),
        resume_filename_format: draft.resume_filename_format.trim() || "{full_name}_{company}_{role}",
        export_formats: draft.export_formats,
        page_budget: Number(draft.page_budget),
        llm_mode: draft.llm_mode || "off",
        llm_model: draft.llm_model,
      });
      await onUpdated();
      setNotice("Settings saved and synced to config/settings.yaml.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save settings.");
    } finally {
      setSaving(false);
    }
  };

  const handleSaveTrack = async () => {
    const track = roleTracks.find((t) => t.id === selectedTrackId);
    if (!track) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateRoleTrack(track.id, {
        aliases: parseListInput(aliasesText),
        keywords: {
          ...track.keywords,
          core_must_have: parseListInput(coreKwText),
          important_systems: parseListInput(sysKwText),
        },
      });
      await onUpdated();
      setNotice(`Updated keyword pack & aliases for ${track.display_name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role track.");
    } finally {
      setSaving(false);
    }
  };

  const handleClearSeen = async (scope: "discarded" | "auto_filtered") => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const res = await api.clearSeenHistory(scope);
      setNotice(
        `Cleared ${res.cleared} ${scope === "discarded" ? "manually discarded" : "auto-filtered"} ledger entries.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear ledger.");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="stack-lg">
      <div className="card row-between">
        <div>
          <h2 style={{ margin: 0, fontSize: 18 }}>Config</h2>
          <div className="muted">
            Synced with <span className="mono">{config.config_path}</span>. Filters apply inline while scraping.
          </div>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => void handleSaveSettings()}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save Settings to YAML"}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <div className="report-grid">
        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Target Roles & Locations</h3>

          <div>
            <label>Target Role Tracks (pulled by default when scraping)</label>
            <div className="row-wrap">
              {roleTracks.map((t) => {
                const selected = draft.target_role_tracks.includes(t.id);
                return (
                  <button
                    key={t.id}
                    type="button"
                    className={`chip ${selected ? "selected" : ""}`}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        target_role_tracks: toggleArrayValue(draft.target_role_tracks, t.id),
                      })
                    }
                  >
                    {t.display_name}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <label>Target Locations (comma-separated cities or Remote)</label>
            <input
              value={locInput}
              onChange={(e) => setLocInput(e.target.value)}
              placeholder="Seattle, WA, San Diego, CA, San Francisco, CA, Remote"
            />
          </div>

          <div className="form-grid-2">
            <div>
              <label>Work Arrangement</label>
              <div className="row-wrap">
                {(["remote", "hybrid", "onsite"] as const).map((wt) => (
                  <button
                    key={wt}
                    type="button"
                    className={`chip ${draft.work_types.includes(wt) ? "selected" : ""}`}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        work_types: toggleArrayValue(draft.work_types, wt),
                      })
                    }
                  >
                    {wt}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <label>Employment Type</label>
              <div className="row-wrap">
                {(["full-time", "contract"] as const).map((jt) => (
                  <button
                    key={jt}
                    type="button"
                    className={`chip ${draft.job_types.includes(jt) ? "selected" : ""}`}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        job_types: toggleArrayValue(draft.job_types, jt),
                      })
                    }
                  >
                    {jt}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="form-grid-2">
            <div>
              <label>Work Authorization Filter</label>
              <select
                value={draft.work_authorization}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    work_authorization: e.target.value as AppSettingsValues["work_authorization"],
                  })
                }
              >
                <option value="h1b">H-1B Sponsorship Friendly</option>
                <option value="any">Any / No Visa Filter</option>
                <option value="us_citizen_gc_only">US Citizen / GC Required</option>
              </select>
            </div>

            <div>
              <label>Default Freshness Window</label>
              <select
                value={draft.posted_within_default}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    posted_within_default: e.target.value as AppSettingsValues["posted_within_default"],
                  })
                }
              >
                <option value="1h">Less than 1 hour ago</option>
                <option value="12h">Less than 12 hours ago</option>
                <option value="24h">Less than 24 hours ago</option>
                <option value="7d">Past 7 days</option>
                <option value="any">Any time</option>
              </select>
            </div>
          </div>
        </div>

        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Compensation, Experience & Quality Filters</h3>

          <div className="form-grid-2">
            <div>
              <label>Min YoE</label>
              <input
                type="number"
                value={draft.target_yoe_min}
                onChange={(e) =>
                  setDraft({ ...draft, target_yoe_min: Number(e.target.value || 0) })
                }
              />
            </div>
            <div>
              <label>Max YoE</label>
              <input
                type="number"
                value={draft.target_yoe_max}
                onChange={(e) =>
                  setDraft({ ...draft, target_yoe_max: Number(e.target.value || 0) })
                }
              />
            </div>
          </div>

          <div className="form-grid-3">
            <div>
              <label>Min Annual Salary (USD)</label>
              <input
                type="number"
                placeholder="Optional (omitted JDs kept)"
                value={draft.target_salary_min ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    target_salary_min: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </div>
            <div>
              <label>Min Hourly Rate ($/hr)</label>
              <input
                type="number"
                placeholder="Optional"
                value={draft.min_hourly_rate ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    min_hourly_rate: e.target.value ? Number(e.target.value) : null,
                  })
                }
              />
            </div>
            <div>
              <label>Min Match Score (0-100)</label>
              <input
                type="number"
                min={0}
                max={100}
                value={draft.min_relevance_score}
                onChange={(e) =>
                  setDraft({ ...draft, min_relevance_score: Number(e.target.value || 0) })
                }
              />
            </div>
          </div>

          <div>
            <label>Title Blocklist (comma-separated excluded terms)</label>
            <input
              value={blocklistInput}
              onChange={(e) => setBlocklistInput(e.target.value)}
              placeholder="intern, junior, entry level, director, recruiter"
            />
          </div>

          <div className="small-note">
            Postings without listed salary stay included.
          </div>
        </div>
      </div>

      <div className="report-grid">
        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Job Sources & Company Boards</h3>

          <div>
            <label>Active Scraper Sources</label>
            <div className="row-wrap">
              {(["greenhouse", "lever", "linkedin"] as const).map((src) => (
                <button
                  key={src}
                  type="button"
                  className={`chip ${draft.scraper_sources.includes(src) ? "selected" : ""}`}
                  onClick={() =>
                    setDraft({
                      ...draft,
                      scraper_sources: toggleArrayValue(draft.scraper_sources, src),
                    })
                  }
                >
                  {src}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label>Company ATS Boards (one per line: provider:slug)</label>
            <textarea
              rows={5}
              value={boardsInput}
              onChange={(e) => setBoardsInput(e.target.value)}
              placeholder={"greenhouse:anthropic\ngreenhouse:databricks\nlever:palantir"}
            />
          </div>
        </div>

        <div className="card stack-md">
          <h3 style={{ margin: 0, fontSize: 15 }}>Export Formatting & Assistant Mode</h3>

          <div>
            <label>Resume Filename Format (tokens: {"{full_name}, {company}, {role}, {location}"})</label>
            <input
              value={draft.resume_filename_format}
              onChange={(e) =>
                setDraft({ ...draft, resume_filename_format: e.target.value })
              }
            />
          </div>

          <div className="form-grid-3">
            <div>
              <label>Export Formats</label>
              <div className="row-wrap">
                {(["pdf", "docx"] as const).map((fmt) => (
                  <button
                    key={fmt}
                    type="button"
                    className={`chip ${draft.export_formats.includes(fmt) ? "selected" : ""}`}
                    onClick={() =>
                      setDraft({
                        ...draft,
                        export_formats: toggleArrayValue(draft.export_formats, fmt),
                      })
                    }
                  >
                    .{fmt}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label>Page Budget</label>
              <select
                value={draft.page_budget}
                onChange={(e) =>
                  setDraft({ ...draft, page_budget: Number(e.target.value) })
                }
              >
                <option value={1}>1 Page (Strict Senior)</option>
                <option value={2}>Up to 2 Pages</option>
              </select>
            </div>
            <div>
              <label>AI Layer Mode</label>
              <select
                value={draft.llm_mode || "off"}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    llm_mode: e.target.value as AppSettingsValues["llm_mode"],
                  })
                }
              >
                <option value="off">Deterministic Only (Fast)</option>
                <option value="ollama_docker">Local Docker LLM (Qwen3 14B)</option>
              </select>
            </div>
          </div>

          <div className="card-elevated row-between">
            <div>
              <strong style={{ fontSize: 13 }}>Deduplication History Reset</strong>
              <div className="small-note">
                Discarded and filtered jobs are permanently skipped across future sessions.
              </div>
            </div>
            <div className="row-wrap">
              <button
                type="button"
                className="btn btn-sm btn-danger-ghost"
                onClick={() => void handleClearSeen("discarded")}
                disabled={saving}
              >
                Reset Discarded
              </button>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => void handleClearSeen("auto_filtered")}
                disabled={saving}
              >
                Reset Auto-Filtered
              </button>
            </div>
          </div>
        </div>
      </div>

      <div className="card stack-md">
        <div className="row-between">
          <div>
            <h3 style={{ margin: 0, fontSize: 15 }}>Role Track Aliases & Weighted Keywords</h3>
            <div className="small-note">
              Customize aliases (like SDE 2, Staff SWE) and skills persisted inside config/role_tracks/*.yaml.
            </div>
          </div>
          <div style={{ minWidth: 240 }}>
            <select
              value={selectedTrackId}
              onChange={(e) => setSelectedTrackId(e.target.value)}
            >
              {roleTracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.display_name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="form-grid-3">
          <div>
            <label>Title Aliases (comma-separated)</label>
            <textarea
              rows={3}
              value={aliasesText}
              onChange={(e) => setAliasesText(e.target.value)}
            />
          </div>
          <div>
            <label>Core Must-Have Keywords (Weight 3.0x)</label>
            <textarea
              rows={3}
              value={coreKwText}
              onChange={(e) => setCoreKwText(e.target.value)}
            />
          </div>
          <div>
            <label>Important Systems Keywords (Weight 2.0x)</label>
            <textarea
              rows={3}
              value={sysKwText}
              onChange={(e) => setSysKwText(e.target.value)}
            />
          </div>
        </div>

        <div className="row-between">
          <span className="small-note">Role file edits take effect immediately for future scrapes & scoring.</span>
          <button
            className="btn"
            onClick={() => void handleSaveTrack()}
            disabled={saving}
          >
            Save Role Track YAML
          </button>
        </div>
      </div>
    </div>
  );
}
