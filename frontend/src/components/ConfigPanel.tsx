import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import {
  buildAvoidedWordsGroups,
  DEFAULT_AVOIDED_AI_WORDS,
  formatJobTypeLabel,
  formatSourceLabel,
  formatWorkTypeLabel,
} from "../constants/tailoring";
import { MultiSelectCheckboxDropdown } from "./MultiSelectCheckboxDropdown";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import type {
  AppSettingsValues,
  ConfigResponse,
  LlmBenchmarkResponse,
  LlmStatusResponse,
  LlmTestResponse,
  LocationCatalogResponse,
  RoleTrackConfig,
} from "../types";

interface ConfigPanelProps {
  config: ConfigResponse | null;
  roleTracks: RoleTrackConfig[];
  onUpdated: () => Promise<void>;
  onDataFlushed?: () => Promise<void>;
}

function parseListInput(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function parseLineInput(raw: string): string[] {
  return raw
    .split(/[\n;]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

export function ConfigPanel({ config, roleTracks, onUpdated, onDataFlushed }: ConfigPanelProps) {
  const [draft, setDraft] = useState<AppSettingsValues | null>(null);
  const [locCatalog, setLocCatalog] = useState<LocationCatalogResponse | null>(null);
  const [locInput, setLocInput] = useState("");
  const [boardsInput, setBoardsInput] = useState("");
  const [blocklistInput, setBlocklistInput] = useState("");

  const [selectedTrackId, setSelectedTrackId] = useState("senior_swe");
  const [aliasesText, setAliasesText] = useState("");
  const [coreKwText, setCoreKwText] = useState("");
  const [sysKwText, setSysKwText] = useState("");

  // Granular & Master Flush controls
  const [flushSessions, setFlushSessions] = useState(true);
  const [flushRuns, setFlushRuns] = useState(true);
  const [flushOutputs, setFlushOutputs] = useState(true);
  const [flushSeen, setFlushSeen] = useState(true);
  const [seenScope, setSeenScope] = useState<"all" | "discarded" | "auto_filtered">("all");
  const [flushResumes, setFlushResumes] = useState(false);
  const [isConfirmingFlush, setIsConfirmingFlush] = useState(false);

  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [llmStatus, setLlmStatus] = useState<LlmStatusResponse | null>(null);
  const [llmBusy, setLlmBusy] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<LlmTestResponse | null>(null);
  const [benchmarkBusy, setBenchmarkBusy] = useState(false);
  const [benchmarkResult, setBenchmarkResult] = useState<LlmBenchmarkResponse | null>(null);
  const [benchmarkCollapsed, setBenchmarkCollapsed] = useState(false);

  const [newBoardProvider, setNewBoardProvider] = useState<"greenhouse" | "lever" | "ashby">("greenhouse");
  const [newBoardSlug, setNewBoardSlug] = useState("");
  const [showRawBoards, setShowRawBoards] = useState(false);
  const [customAvoidedWord, setCustomAvoidedWord] = useState("");

  const refreshLlmStatus = async () => {
    try {
      const st = await api.getLlmStatus();
      setLlmStatus(st);
    } catch {
      // keep existing status
    }
  };

  useEffect(() => {
    void api.getLocations().then(setLocCatalog).catch(() => {});
    void refreshLlmStatus();
  }, []);

  useEffect(() => {
    if (!config) return;
    setDraft(config.values);
    setLocInput(config.values.target_locations.join("\n"));
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

  const locationGroups = useMemo(() => {
    const top20 = locCatalog?.top_20 ?? [
      "Seattle, WA",
      "San Francisco, CA",
      "New York, NY",
      "San Jose, CA",
      "Austin, TX",
      "San Diego, CA",
      "Boston, MA",
      "Los Angeles, CA",
      "Remote",
    ];
    const otherUs = locCatalog?.other_us ?? [];
    const groups = [
      {
        title: "Top 20 US Tech Cities",
        items: top20.map((city) => ({ value: city, label: city })),
      },
    ];
    if (otherUs.length > 0) {
      groups.push({
        title: "All US Tech Cities (A-Z)",
        items: otherUs.map((city) => ({ value: city, label: city })),
      });
    }
    return groups;
  }, [locCatalog]);

  const parsedLocations = useMemo(() => parseLineInput(locInput), [locInput]);

  const parsedBoards = useMemo(() => {
    return boardsInput
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((line) => {
        const parts = line.split(":");
        const provider = parts.length > 1 ? parts[0].trim().toLowerCase() : "greenhouse";
        const slug = parts.length > 1 ? parts.slice(1).join(":").trim() : parts[0].trim();
        return { line, provider, slug };
      });
  }, [boardsInput]);

  if (!config || !draft) {
    return <div className="card muted">Loading configuration...</div>;
  }

  const toggleArrayValue = <T extends string>(arr: T[], val: T): T[] =>
    arr.includes(val) ? arr.filter((x) => x !== val) : [...arr, val];

  const handleAddBoard = () => {
    const slug = newBoardSlug.trim().toLowerCase();
    if (!slug) return;
    const line = `${newBoardProvider}:${slug}`;
    if (!boardsInput.includes(line)) {
      const next = boardsInput ? `${boardsInput}\n${line}` : line;
      setBoardsInput(next);
    }
    setNewBoardSlug("");
  };

  const handleRemoveBoard = (lineToRemove: string) => {
    const next = boardsInput
      .split("\n")
      .filter((l) => l.trim() !== lineToRemove)
      .join("\n");
    setBoardsInput(next);
  };

  const handleAddCustomAvoidedWord = () => {
    const word = customAvoidedWord.trim().toLowerCase();
    if (!word || !draft) return;
    const current = draft.avoided_ai_words ?? DEFAULT_AVOIDED_AI_WORDS;
    if (!current.includes(word)) {
      setDraft({ ...draft, avoided_ai_words: [...current, word] });
      setNotice(`Added blocked word "${word}". Click 'Save Settings' to persist.`);
    }
    setCustomAvoidedWord("");
  };

  const handleSaveSettings = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      await api.updateConfig({
        target_role_tracks: draft.target_role_tracks,
        target_locations: parseLineInput(locInput),
        work_types: draft.work_types,
        job_types: draft.job_types,
        work_authorization: draft.work_authorization,
        posted_within_default: draft.posted_within_default,
        target_yoe_min:
          draft.target_yoe_min === null || Number.isNaN(draft.target_yoe_min)
            ? null
            : Number(draft.target_yoe_min),
        target_yoe_max:
          draft.target_yoe_max === null || Number.isNaN(draft.target_yoe_max)
            ? null
            : Number(draft.target_yoe_max),
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
        default_bullets_per_role: Number(draft.default_bullets_per_role || 5),
        avoided_ai_words: draft.avoided_ai_words ?? DEFAULT_AVOIDED_AI_WORDS,
        custom_tailor_instructions: draft.custom_tailor_instructions || "",
        llm_mode: draft.llm_mode || "off",
        llm_model: (draft.llm_model || "").trim() || "mistral-nemo:latest",
        ollama_base_url: (draft.ollama_base_url || "").trim() || "http://localhost:11434",
        strict_humanizer_gate: Boolean(draft.strict_humanizer_gate),
      });
      await onUpdated();
      await refreshLlmStatus();
      setNotice("Settings saved and applied.");
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

  const applyPresetKeepResumes = () => {
    setFlushSessions(true);
    setFlushRuns(true);
    setFlushOutputs(true);
    setFlushSeen(true);
    setFlushResumes(false);
    setIsConfirmingFlush(false);
  };

  const applyPresetAll = () => {
    setFlushSessions(true);
    setFlushRuns(true);
    setFlushOutputs(true);
    setFlushSeen(true);
    setFlushResumes(true);
    setIsConfirmingFlush(false);
  };

  const applyPresetClear = () => {
    setFlushSessions(false);
    setFlushRuns(false);
    setFlushOutputs(false);
    setFlushSeen(false);
    setFlushResumes(false);
    setIsConfirmingFlush(false);
  };

  const handleFlushData = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const isMasterPreset =
        flushSessions && flushRuns && flushOutputs && flushSeen && !flushResumes;
      const res = await api.flushData({
        master_flush: isMasterPreset,
        flush_sessions_and_jobs: flushSessions,
        flush_tailoring_runs: flushRuns,
        flush_output_files: flushOutputs,
        flush_seen_history: flushSeen,
        seen_scope: seenScope,
        flush_resumes: flushResumes,
      });
      setIsConfirmingFlush(false);
      try {
        localStorage.removeItem("careerflow.jobProgress.v1");
        localStorage.removeItem("careerflow.jobDrafts.v1");
        localStorage.removeItem("careerflow.tailorHistory.v1");
        window.dispatchEvent(new CustomEvent("careerflow.dataFlushed"));
      } catch {
        // ignore storage errors
      }
      if (onDataFlushed) {
        await onDataFlushed();
      }
      setNotice(
        `Flushed: ${res.sessions_deleted} sessions, ${res.jobs_deleted} jobs, ${res.tailoring_runs_deleted} tailoring runs, ${res.seen_deleted} seen entries, ${res.output_items_deleted} output items` +
          (res.resumes_deleted > 0 ? `, ${res.resumes_deleted} resumes.` : " (resumes & config preserved).")
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to flush data.");
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
            Filters, recruiting sources, and tailoring controls apply inline during scraping and tailoring.
          </div>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => void handleSaveSettings()}
          disabled={saving}
        >
          {saving ? "Saving..." : "Save Settings"}
        </button>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      <div className="report-grid">
        <div className="card stack-md" style={{ overflow: "hidden" }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Target Role Tracks</h3>

          <div className="stack-sm">
            <div className="row-between">
              <label style={{ marginBottom: 0 }}>
                Target Role Tracks (with typical company YoE expectations)
              </label>
              <div className="row-wrap">
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      target_role_tracks: roleTracks
                        .filter((t) => t.id === "mid_swe" || t.id === "senior_swe")
                        .map((t) => t.id),
                    })
                  }
                >
                  Mid + Senior (2–8 yrs)
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      target_role_tracks: roleTracks
                        .filter((t) => t.id === "staff_swe" || t.id === "principal_swe")
                        .map((t) => t.id),
                    })
                  }
                >
                  Staff+ (8+ yrs)
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => {
                    const dataTracks = ["data_engineer", "data_scientist", "ai_engineer", "ml_engineer", "mlops_ai_infra"];
                    setDraft({
                      ...draft,
                      target_role_tracks: roleTracks
                        .filter((t) => dataTracks.includes(t.id))
                        .map((t) => t.id),
                    });
                  }}
                >
                  Data &amp; AI (3–8 yrs)
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() =>
                    setDraft({
                      ...draft,
                      target_role_tracks: roleTracks.map((t) => t.id),
                    })
                  }
                >
                  All Roles
                </button>
              </div>
            </div>

            {[
              { title: "Company Seniority Levels", key: "swe_levels" },
              { title: "AI, Machine Learning & Data", key: "ai_data" },
              { title: "Backend, Product, Startup, Field & Cloud", key: "engineering_specialty" },
            ].map((grp) => {
              const items = roleTracks.filter((t) =>
                grp.key === "engineering_specialty"
                  ? t.category !== "swe_levels" && t.category !== "ai_data"
                  : t.category === grp.key
              );
              if (items.length === 0) return null;
              return (
                <div key={grp.key} className="stack-sm" style={{ gap: 6 }}>
                  <div className="small-note" style={{ fontWeight: 700, textTransform: "uppercase" }}>
                    {grp.title}
                  </div>
                  <div className="row-wrap">
                    {items.map((t) => {
                      const selected = draft.target_role_tracks.includes(t.id);
                      const yoe =
                        t.typical_yoe_label ||
                        (t.target_yoe_range.length >= 2
                          ? `${t.target_yoe_range[0]}–${t.target_yoe_range[1]} yrs`
                          : "");
                      const tooltip = [
                        yoe ? `Typical YoE: ${yoe}` : "",
                        t.company_examples?.length
                          ? `Examples: ${t.company_examples.join(" · ")}`
                          : "",
                        t.description,
                      ]
                        .filter(Boolean)
                        .join("\n");
                      return (
                        <button
                          key={t.id}
                          type="button"
                          className={`chip ${selected ? "selected" : ""}`}
                          title={tooltip}
                          onClick={() =>
                            setDraft({
                              ...draft,
                              target_role_tracks: toggleArrayValue(draft.target_role_tracks, t.id),
                            })
                          }
                        >
                          <span>{t.display_name}</span>
                          {yoe && <span className="role-chip-yoe">({yoe})</span>}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="card stack-md" style={{ overflow: "hidden" }}>
          <h3 style={{ margin: 0, fontSize: 15 }}>Target Locations &amp; Filters</h3>

          <div className="stack-sm">
            <MultiSelectCheckboxDropdown
              label="Target Locations (US Tech Hubs Picker)"
              summaryText={
                parsedLocations.includes("ALL_US")
                  ? "All US Tech Cities"
                  : parsedLocations.length === 0
                  ? "Any Location (Select cities)"
                  : `${parsedLocations.length} selected: ${parsedLocations.slice(0, 2).join(", ")}${
                      parsedLocations.length > 2 ? "…" : ""
                    }`
              }
              groups={locationGroups}
              selected={parsedLocations}
              onChange={(next) => setLocInput(next.join("\n"))}
              searchPlaceholder="Search US city or state..."
              quickActions={[
                {
                  label: "Top 20 Cities",
                  onClick: () => setLocInput((locCatalog?.top_20 ?? []).join("\n")),
                },
                {
                  label: "All US Cities",
                  active: parsedLocations.includes("ALL_US"),
                  onClick: () => setLocInput("ALL_US"),
                },
                {
                  label: "Clear",
                  onClick: () => setLocInput(""),
                },
              ]}
            />
            <AutoGrowTextarea
              minHeight={52}
              value={locInput}
              onChange={(e) => setLocInput(e.target.value)}
              placeholder={"One location per line (e.g.\nSeattle, WA\nSan Francisco, CA\nRemote)"}
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
                    {formatWorkTypeLabel(wt)}
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
                    {formatJobTypeLabel(jt)}
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

          <div className="form-grid-2">
            <div>
              <label>Min YoE (optional)</label>
              <input
                type="number"
                min={0}
                max={20}
                placeholder="Empty = no min YoE filter"
                value={draft.target_yoe_min ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    target_yoe_min: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
            </div>
            <div>
              <label>Max YoE (optional)</label>
              <input
                type="number"
                min={0}
                max={25}
                placeholder="Empty = no max YoE filter"
                value={draft.target_yoe_max ?? ""}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    target_yoe_max: e.target.value === "" ? null : Number(e.target.value),
                  })
                }
              />
            </div>
          </div>
          <div className="small-note">
            Leave Min YoE or Max YoE empty to disable experience-year filtering during scrapes.
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
            <AutoGrowTextarea
              minHeight={42}
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
        {/* Left Column: Job Sources + Local AI Engine + Blocked Words & Custom Instructions */}
        <div className="stack-md">
          {/* Card 1: Job Sources */}
          <div className="card stack-md" style={{ overflow: "hidden" }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>Job Sources</h3>

            <div>
              <label>Active Scraper Sources</label>
              <div className="row-wrap">
                {(["linkedin", "greenhouse", "ashby", "lever"] as const).map((src) => (
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
                    {formatSourceLabel(src)}
                  </button>
                ))}
              </div>
            </div>

            <div>
              <div className="row-between" style={{ marginBottom: 6 }}>
                <label style={{ marginBottom: 0 }}>Company ATS Boards ({parsedBoards.length} boards configured)</label>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => setShowRawBoards((v) => !v)}
                >
                  {showRawBoards ? "View as Badges" : "Edit as Raw Text"}
                </button>
              </div>

              {!showRawBoards ? (
                <div className="stack-sm">
                  <div className="company-board-grid">
                    {parsedBoards.length === 0 ? (
                      <div className="small-note">No company boards added yet. Add below or paste raw lines.</div>
                    ) : (
                      parsedBoards.map((b) => (
                        <div key={b.line} className="board-badge-chip">
                          <span className={`board-provider-tag board-provider-${b.provider}`}>
                            {b.provider}
                          </span>
                          <span style={{ fontWeight: 600 }}>{b.slug}</span>
                          <button
                            type="button"
                            className="board-chip-remove"
                            title={`Remove ${b.line}`}
                            onClick={() => handleRemoveBoard(b.line)}
                          >
                            &times;
                          </button>
                        </div>
                      ))
                    )}
                  </div>

                  <div className="row-wrap" style={{ gap: 6, alignItems: "center" }}>
                    <select
                      style={{ width: "auto", minWidth: 120 }}
                      value={newBoardProvider}
                      onChange={(e) =>
                        setNewBoardProvider(e.target.value as "greenhouse" | "lever" | "ashby")
                      }
                    >
                      <option value="greenhouse">Greenhouse</option>
                      <option value="lever">Lever</option>
                      <option value="ashby">Ashby</option>
                    </select>
                    <input
                      style={{ flex: 1, minWidth: 160 }}
                      value={newBoardSlug}
                      onChange={(e) => setNewBoardSlug(e.target.value)}
                      placeholder="Company slug (e.g. anthropic, stripe)"
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          handleAddBoard();
                        }
                      }}
                    />
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={handleAddBoard}
                    >
                      + Add Board
                    </button>
                  </div>
                </div>
              ) : (
                <AutoGrowTextarea
                  minHeight={110}
                  value={boardsInput}
                  onChange={(e) => setBoardsInput(e.target.value)}
                  placeholder={"greenhouse:anthropic\ngreenhouse:databricks\nlever:palantir"}
                />
              )}
            </div>
          </div>

          {/* Card 2: Local AI Engine */}
          <div className="card stack-sm" style={{ overflow: "hidden" }}>
            <div className="row-between">
              <div>
                <strong style={{ fontSize: 14 }}>Local AI Engine</strong>
                <div className="small-note">
                  Local open-source model handles XYZ resume tailoring, 5-year generation, and humanization.
                </div>
              </div>
              <div className="row-wrap">
                {llmStatus && (
                  <span className={`pill ${llmStatus.reachable ? "pill-green" : "pill-amber"}`}>
                    {llmStatus.reachable
                      ? `Connected · ${llmStatus.available_models.length} model(s)`
                      : "Ollama Offline / Unreachable"}
                  </span>
                )}
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={llmBusy}
                  onClick={async () => {
                    setLlmBusy(true);
                    setLlmTestResult(null);
                    await refreshLlmStatus();
                    setLlmBusy(false);
                  }}
                >
                  Refresh Models
                </button>
                <button
                  type="button"
                  className="btn btn-sm btn-primary"
                  disabled={llmBusy || benchmarkBusy}
                  onClick={async () => {
                    setLlmBusy(true);
                    setError(null);
                    try {
                      const res = await api.testLlm(draft.llm_model, draft.ollama_base_url);
                      setLlmTestResult(res);
                    } catch (err) {
                      setLlmTestResult({
                        ok: false,
                        model: draft.llm_model,
                        latency_ms: 0,
                        sample_output: "",
                        error: err instanceof Error ? err.message : "Test failed.",
                      });
                    } finally {
                      setLlmBusy(false);
                    }
                  }}
                >
                  {llmBusy ? "Testing..." : "Test Model"}
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  disabled={llmBusy || benchmarkBusy}
                  onClick={async () => {
                    setBenchmarkBusy(true);
                    setError(null);
                    try {
                      const res = await api.benchmarkLlm(null, draft.ollama_base_url);
                      setBenchmarkResult(res);
                    } catch (err) {
                      setError(err instanceof Error ? err.message : "Model benchmark failed.");
                    } finally {
                      setBenchmarkBusy(false);
                    }
                  }}
                >
                  {benchmarkBusy ? "Benchmarking..." : "Rank Models"}
                </button>
              </div>
            </div>

            <div className="form-grid-3">
              <div>
                <label>Active Model</label>
                {llmStatus?.available_models.length ? (
                  <select
                    value={
                      llmStatus.available_models.includes(draft.llm_model)
                        ? draft.llm_model
                        : "__custom__"
                    }
                    onChange={(e) => {
                      if (e.target.value !== "__custom__") {
                        setDraft({ ...draft, llm_model: e.target.value });
                      }
                    }}
                  >
                    {llmStatus.available_models.map((m) => (
                      <option key={m} value={m}>
                        {m}
                        {m === llmStatus.recommended_model ? " (Recommended)" : ""}
                      </option>
                    ))}
                    {!llmStatus.available_models.includes(draft.llm_model) && (
                      <option value="__custom__">Custom: {draft.llm_model}</option>
                    )}
                  </select>
                ) : (
                  <input
                    value={draft.llm_model}
                    onChange={(e) => setDraft({ ...draft, llm_model: e.target.value })}
                    placeholder="mistral-nemo:latest"
                  />
                )}
              </div>

              <div>
                <label>Ollama Endpoint</label>
                <input
                  value={draft.ollama_base_url}
                  onChange={(e) => setDraft({ ...draft, ollama_base_url: e.target.value })}
                  placeholder="http://localhost:11434"
                />
              </div>

              <div style={{ display: "flex", alignItems: "flex-end", paddingBottom: 4 }}>
                <label className="checkbox-row" style={{ margin: 0, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={Boolean(draft.strict_humanizer_gate)}
                    onChange={(e) =>
                      setDraft({ ...draft, strict_humanizer_gate: e.target.checked })
                    }
                  />
                  <span>Anti-AI Humanizer</span>
                </label>
              </div>
            </div>

            {llmTestResult && (
              <div className={`alert ${llmTestResult.ok ? "alert-success" : "alert-error"}`}>
                {llmTestResult.ok ? (
                  <div>
                    ✓ Model <strong>{llmTestResult.model}</strong> is active and responsive (
                    <strong>{llmTestResult.latency_ms}ms</strong>). Generated Google XYZ bullet:
                    <div style={{ marginTop: 6, fontStyle: "italic", fontSize: 13, background: "rgba(0,0,0,0.25)", padding: "6px 10px", borderRadius: 4 }}>
                      "{llmTestResult.sample_output}"
                    </div>
                  </div>
                ) : (
                  <>Test failed for {llmTestResult.model}: {llmTestResult.error}</>
                )}
              </div>
            )}

            {benchmarkResult && (
              <div className="card stack-sm" style={{ padding: 12 }}>
                <div className="row-between" style={{ alignItems: "center" }}>
                  <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                    <strong style={{ fontSize: 13 }}>
                      Model Benchmark &amp; Ranking
                    </strong>
                    {benchmarkResult.recommended_model && (
                      <span className="pill pill-green">
                        Top Pick: {benchmarkResult.recommended_model}
                      </span>
                    )}
                  </div>
                  <div className="row-wrap" style={{ gap: 6 }}>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setBenchmarkCollapsed((v) => !v)}
                    >
                      {benchmarkCollapsed ? "▸ Expand Benchmark" : "▾ Collapse Benchmark"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setBenchmarkResult(null)}
                      title="Dismiss benchmark table"
                      style={{ padding: "2px 8px" }}
                    >
                      &times;
                    </button>
                  </div>
                </div>
                {!benchmarkCollapsed && (
                  !benchmarkResult.reachable ? (
                    <div className="small-note">
                      Ollama endpoint {benchmarkResult.base_url} is not reachable.
                    </div>
                  ) : (
                    <div style={{ overflowX: "auto" }}>
                      <table className="data-table">
                        <thead>
                          <tr>
                            <th>Rank</th>
                            <th>Model</th>
                            <th>Score</th>
                            <th>Speed</th>
                            <th>JSON / Completeness</th>
                            <th>Stack Accuracy</th>
                            <th>Action</th>
                          </tr>
                        </thead>
                        <tbody>
                          {benchmarkResult.items.map((item) => {
                            const isActive = draft.llm_model === item.model;
                            return (
                              <tr key={item.model}>
                                <td className="mono">
                                  <strong>#{item.rank}</strong>
                                </td>
                                <td>
                                  <strong>{item.model}</strong>
                                  {item.rank === 1 && item.ok && (
                                    <span className="pill pill-green" style={{ marginLeft: 6 }}>
                                      Top Pick
                                    </span>
                                  )}
                                </td>
                                <td className="mono">
                                  <strong>{item.score.toFixed(1)}</strong>/100
                                </td>
                                <td className="mono">{(item.latency_ms / 1000).toFixed(1)}s</td>
                                <td>
                                  <span className={`pill ${item.schema_complete ? "pill-green" : item.json_valid ? "pill-blue" : "pill-amber"}`}>
                                    {item.schema_complete ? "Full Schema" : item.json_valid ? "Valid JSON" : "Failed"}
                                  </span>
                                </td>
                                <td className="small-note">{item.notes}</td>
                                <td>
                                  <button
                                    type="button"
                                    className={`btn btn-sm ${isActive ? "" : "btn-primary"}`}
                                    disabled={isActive || !item.ok}
                                    onClick={() => {
                                      setDraft({ ...draft, llm_model: item.model });
                                      setNotice(`Selected '${item.model}' (Rank #${item.rank}). Click Save Settings to persist.`);
                                    }}
                                  >
                                    {isActive ? "Active" : "Use Model"}
                                  </button>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )
                )}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Export Settings + Blocked Words + Reset Workspace */}
        <div className="stack-md">
          {/* Card 1: Export Settings */}
          <div className="card stack-md" style={{ overflow: "hidden" }}>
            <h3 style={{ margin: 0, fontSize: 15 }}>Export Settings</h3>

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
                <label>Pages</label>
                <select
                  value={draft.page_budget}
                  onChange={(e) =>
                    setDraft({ ...draft, page_budget: Number(e.target.value) })
                  }
                >
                  <option value={1}>1 Page (Strict Senior)</option>
                  <option value={1.5}>1.5 Pages (Balanced)</option>
                  <option value={2}>Up to 2 Pages</option>
                  <option value={3}>3 Pages (Deep Tech)</option>
                </select>
              </div>
              <div>
                <label>Default Bullets / Experience</label>
                <select
                  value={draft.default_bullets_per_role || 5}
                  onChange={(e) =>
                    setDraft({ ...draft, default_bullets_per_role: Number(e.target.value) || 5 })
                  }
                >
                  {[3, 4, 5, 6, 7, 8, 10].map((n) => (
                    <option key={n} value={n}>
                      {n} bullets / experience
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label>AI Engine</label>
              <select
                value={draft.llm_mode || "off"}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    llm_mode: e.target.value as AppSettingsValues["llm_mode"],
                  })
                }
              >
                <option value="ollama_local">Local Ollama AI (Single Model — Recommended)</option>
                <option value="off">Deterministic Rules Only (Fast)</option>
                <option value="ollama_docker">Local Docker AI (Ollama Container)</option>
              </select>
            </div>
          </div>

          {/* Card 2: Blocked Words & Instructions */}
          <div className="card stack-sm" style={{ overflow: "hidden" }}>
            <strong style={{ fontSize: 14 }}>Blocked Words &amp; Instructions</strong>
            <div className="form-grid-2" style={{ marginTop: 4 }}>
              <div>
                <MultiSelectCheckboxDropdown
                  label="Blocked Words (uncheck any word to permit it)"
                  summaryText={`${(draft.avoided_ai_words ?? DEFAULT_AVOIDED_AI_WORDS).length} blocked words active`}
                  groups={buildAvoidedWordsGroups(draft.avoided_ai_words ?? DEFAULT_AVOIDED_AI_WORDS)}
                  selected={draft.avoided_ai_words ?? DEFAULT_AVOIDED_AI_WORDS}
                  onChange={(next) => setDraft({ ...draft, avoided_ai_words: next })}
                  quickActions={[
                    {
                      label: "Recommended Banlist",
                      onClick: () => setDraft({ ...draft, avoided_ai_words: [...DEFAULT_AVOIDED_AI_WORDS] }),
                    },
                    {
                      label: "Allow All",
                      onClick: () => setDraft({ ...draft, avoided_ai_words: [] }),
                    },
                  ]}
                />
                <div className="blocked-word-adder">
                  <input
                    value={customAvoidedWord}
                    onChange={(e) => setCustomAvoidedWord(e.target.value)}
                    placeholder="Add custom blocked word (e.g. spearheaded, synergy)"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        handleAddCustomAvoidedWord();
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={handleAddCustomAvoidedWord}
                  >
                    + Add Blocked Word
                  </button>
                </div>
              </div>
              <div>
                <label>Custom Instructions (sent to LLM)</label>
                <AutoGrowTextarea
                  minHeight={68}
                  value={draft.custom_tailor_instructions || ""}
                  onChange={(e) =>
                    setDraft({ ...draft, custom_tailor_instructions: e.target.value })
                  }
                  placeholder="e.g., Emphasize distributed systems & GenAI APIs; keep tone concrete"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Reset Workspace (Full Width) */}
      {(() => {
        const hasFlushSelection =
          flushSessions || flushRuns || flushOutputs || flushSeen || flushResumes;
        const isAllFlushSelected =
          flushSessions && flushRuns && flushOutputs && flushSeen && flushResumes;
        const isMasterFlushPreset =
          flushSessions && flushRuns && flushOutputs && flushSeen && !flushResumes;

        let flushButtonLabel = "Flush Selected Data";
        if (!hasFlushSelection) {
          flushButtonLabel = "Select Data to Flush";
        } else if (isAllFlushSelected) {
          flushButtonLabel = "Flush All (Includes Resumes)";
        } else if (isMasterFlushPreset) {
          flushButtonLabel = "Master Flush (Keep Resumes)";
        } else if (flushResumes) {
          flushButtonLabel = "Flush Selected (Includes Resumes)";
        }

        return (
          <div className="card stack-md" style={{ overflow: "hidden" }}>
            <div className="row-between" style={{ alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <div>
                <strong style={{ fontSize: 14 }}>Reset Workspace</strong>
                <div className="small-note">
                  Clean test runs or reset workspace data. Choose options below, then flush.
                </div>
              </div>
              <div className="row-wrap" style={{ gap: 6 }}>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ fontSize: 11, padding: "4px 9px" }}
                  onClick={applyPresetKeepResumes}
                  title="Select all data except saved resumes"
                >
                  Master Preset (Keep Resumes)
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ fontSize: 11, padding: "4px 9px" }}
                  onClick={applyPresetAll}
                  title="Select all data including saved resumes"
                >
                  Select All
                </button>
                <button
                  type="button"
                  className="btn btn-sm"
                  style={{ fontSize: 11, padding: "4px 9px" }}
                  onClick={applyPresetClear}
                  title="Deselect all"
                >
                  Clear
                </button>
              </div>
            </div>

            <div className="flush-grid">
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={flushSessions}
                  onChange={(e) => {
                    setFlushSessions(e.target.checked);
                    setIsConfirmingFlush(false);
                  }}
                />
                <span>Sessions &amp; Scraped Jobs</span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={flushRuns}
                  onChange={(e) => {
                    setFlushRuns(e.target.checked);
                    setIsConfirmingFlush(false);
                  }}
                />
                <span>Tailoring Runs</span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={flushOutputs}
                  onChange={(e) => {
                    setFlushOutputs(e.target.checked);
                    setIsConfirmingFlush(false);
                  }}
                />
                <span>Exported Output Files</span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={flushSeen}
                  onChange={(e) => {
                    setFlushSeen(e.target.checked);
                    setIsConfirmingFlush(false);
                  }}
                />
                <span>Seen / Dedup Ledger</span>
              </label>
              <label className="checkbox-row">
                <input
                  type="checkbox"
                  checked={flushResumes}
                  onChange={(e) => {
                    setFlushResumes(e.target.checked);
                    setIsConfirmingFlush(false);
                  }}
                />
                <span style={flushResumes ? { color: "#ff6961", fontWeight: 600 } : undefined}>
                  Saved Resumes {flushResumes && "(Deletes Resumes)"}
                </span>
              </label>
            </div>

            <div className="row-between" style={{ alignItems: "center", gap: 12, flexWrap: "wrap" }}>
              <div className="row-wrap" style={{ alignItems: "center" }}>
                {flushSeen && (
                  <div style={{ minWidth: 200 }}>
                    <select
                      value={seenScope}
                      onChange={(e) =>
                        setSeenScope(e.target.value as "all" | "discarded" | "auto_filtered")
                      }
                    >
                      <option value="all">Seen Ledger: All</option>
                      <option value="discarded">Seen Ledger: Discarded Only</option>
                      <option value="auto_filtered">Seen Ledger: Auto-Filtered Only</option>
                    </select>
                  </div>
                )}
              </div>

              <div>
                {isConfirmingFlush ? (
                  <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 12, color: "#ff6961", fontWeight: 600 }}>
                      {flushResumes
                        ? "⚠️ Resumes will be permanently deleted!"
                        : "Are you sure you want to flush?"}
                    </span>
                    <button
                      type="button"
                      className="btn btn-sm btn-danger-ghost"
                      onClick={() => void handleFlushData()}
                      disabled={saving}
                    >
                      Confirm Flush
                    </button>
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setIsConfirmingFlush(false)}
                      disabled={saving}
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className={`btn ${flushResumes ? "btn-danger-ghost" : ""}`}
                    disabled={saving || !hasFlushSelection}
                    onClick={() => setIsConfirmingFlush(true)}
                  >
                    {flushButtonLabel}
                  </button>
                )}
              </div>
            </div>
          </div>
        );
      })()}

      <div className="card stack-md" style={{ overflow: "hidden" }}>
        <div className="row-between">
          <div>
            <h3 style={{ margin: 0, fontSize: 15 }}>
              Track Aliases &amp; Keywords
            </h3>
            <div className="small-note">
              See typical YoE &amp; company equivalents (e.g., Staff = L6 / E6 / 8–12+ yrs) and customize role aliases, target levels, or skills below.
            </div>
          </div>
          <div style={{ minWidth: 280 }}>
            <select
              value={selectedTrackId}
              onChange={(e) => setSelectedTrackId(e.target.value)}
            >
              {roleTracks.map((t) => {
                const yoe =
                  t.typical_yoe_label ||
                  (t.target_yoe_range.length >= 2
                    ? `${t.target_yoe_range[0]}–${t.target_yoe_range[1]} yrs`
                    : "");
                return (
                  <option key={t.id} value={t.id}>
                    {t.display_name} {yoe ? `(${yoe})` : ""}
                  </option>
                );
              })}
            </select>
          </div>
        </div>

        {(() => {
          const activeTrack = roleTracks.find((t) => t.id === selectedTrackId);
          if (!activeTrack) return null;
          const yoe =
            activeTrack.typical_yoe_label ||
            (activeTrack.target_yoe_range.length >= 2
              ? `${activeTrack.target_yoe_range[0]}–${activeTrack.target_yoe_range[1]} yrs`
              : "Varies");
          return (
            <div className="role-meta-banner">
              <div className="row-wrap">
                <span className="pill pill-blue mono">Typical YoE: {yoe}</span>
                {activeTrack.search_query && (
                  <span className="pill">LinkedIn Query: {activeTrack.search_query}</span>
                )}
              </div>
              {activeTrack.company_examples && activeTrack.company_examples.length > 0 && (
                <div className="small-note">
                  <strong>Company Title Equivalents:</strong>{" "}
                  {activeTrack.company_examples.join(" · ")}
                </div>
              )}
              {activeTrack.description && (
                <div className="small-note">{activeTrack.description}</div>
              )}
            </div>
          );
        })()}

        <div className="form-grid-3">
          <div style={{ minWidth: 0 }}>
            <label>Title Aliases (comma-separated)</label>
            <AutoGrowTextarea
              minHeight={85}
              value={aliasesText}
              onChange={(e) => setAliasesText(e.target.value)}
            />
          </div>
          <div style={{ minWidth: 0 }}>
            <label>Core Must-Have Keywords (Weight 3.0x)</label>
            <AutoGrowTextarea
              minHeight={85}
              value={coreKwText}
              onChange={(e) => setCoreKwText(e.target.value)}
            />
          </div>
          <div style={{ minWidth: 0 }}>
            <label>Important Systems Keywords (Weight 2.0x)</label>
            <AutoGrowTextarea
              minHeight={85}
              value={sysKwText}
              onChange={(e) => setSysKwText(e.target.value)}
            />
          </div>
        </div>

        <div className="row-between">
          <span className="small-note">Role track updates take effect immediately for future scrapes &amp; scoring.</span>
          <button
            className="btn"
            onClick={() => void handleSaveTrack()}
            disabled={saving}
          >
            Save Role Track
          </button>
        </div>
      </div>
    </div>
  );
}
