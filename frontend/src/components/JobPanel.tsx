import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { formatEasternDateTime } from "../utils/datetime";
import { formatSourceLabel } from "../constants/tailoring";
import {
  MultiSelectCheckboxDropdown,
  type DropdownOptionGroup,
} from "./MultiSelectCheckboxDropdown";
import { SessionJobsWorkspace } from "./SessionJobsWorkspace";
import { AutoGrowTextarea } from "./AutoGrowTextarea";
import type {
  ConfigResponse,
  JobPostingResponse,
  LocationCatalogResponse,
  ResumeListResponse,
  RoleTrackConfig,
  ScrapeBatchResult,
  ScrapeProgressResponse,
  ScrapeSessionSummary,
  SessionFilteredJobResponse,
  TabId,
} from "../types";

interface JobPanelProps {
  config: ConfigResponse | null;
  sessions: ScrapeSessionSummary[];
  activeSessionId: number | null;
  onSelectSession: (id: number) => void;
  roleTracks: RoleTrackConfig[];
  resumeState: ResumeListResponse | null;
  onSessionsChanged: (selectId?: number) => Promise<void>;
  onResumesChanged?: () => Promise<void>;
  onNavigateTab: (tab: TabId) => void;
  viewportMode?: "standard" | "wide" | "maximized";
  onChangeViewportMode?: (mode: "standard" | "wide" | "maximized") => void;
}

const FRESHNESS_OPTIONS = [
  { value: "1h", label: "Less than 1 hour ago" },
  { value: "12h", label: "Less than 12 hours ago" },
  { value: "24h", label: "Less than 24 hours ago" },
  { value: "7d", label: "Past 7 days" },
  { value: "any", label: "Any time" },
];

const SOURCE_LABELS: Record<string, string> = {
  linkedin: "LinkedIn Public Search",
  greenhouse: "Greenhouse Boards",
  ashby: "Ashby Boards",
  lever: "Lever Boards",
};

function formatBoardLabel(entry: string): string {
  const [provider, slug] = entry.split(":", 2);
  if (!slug) return entry;
  const company = slug.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  return `${company} (${formatSourceLabel(provider)})`;
}

export function JobPanel({
  config,
  sessions,
  activeSessionId,
  onSelectSession,
  roleTracks,
  resumeState,
  onSessionsChanged,
  onResumesChanged,
  onNavigateTab,
  viewportMode = "maximized",
  onChangeViewportMode,
}: JobPanelProps) {
  const [locCatalog, setLocCatalog] = useState<LocationCatalogResponse | null>(null);
  const [expandedSessionId, setExpandedSessionId] = useState<number | null>(activeSessionId);
  const [jobsBySession, setJobsBySession] = useState<Record<number, JobPostingResponse[]>>({});
  const [discardedBySession, setDiscardedBySession] = useState<Record<number, JobPostingResponse[]>>({});
  const [filteredBySession, setFilteredBySession] = useState<
    Record<number, SessionFilteredJobResponse[]>
  >({});
  const [loadingJobsFor, setLoadingJobsFor] = useState<number | null>(null);

  // Session creation & pre-scrape filters
  const [newSessionName, setNewSessionName] = useState("");
  const [freshness, setFreshness] = useState<string>(
    config?.values.posted_within_default || "24h"
  );
  const [selectedRoleTracks, setSelectedRoleTracks] = useState<string[]>([]);
  const [selectedSourceKeys, setSelectedSourceKeys] = useState<string[]>([]);
  const [selectedLocations, setSelectedLocations] = useState<string[]>([]);
  const initializedFiltersRef = useRef(false);

  // Live scrape progress state
  const [scrapingSessionId, setScrapingSessionId] = useState<number | null>(null);
  const [stoppingScrape, setStoppingScrape] = useState(false);
  const [liveProgress, setLiveProgress] = useState<ScrapeProgressResponse | null>(null);
  const [batchResult, setBatchResult] = useState<ScrapeBatchResult | null>(null);

  // Manual URL / Paste JD drawer (kept as requested)
  const [showManualDrawer, setShowManualDrawer] = useState(false);
  const [manualUrl, setManualUrl] = useState("");
  const [manualText, setManualText] = useState("");
  const [manualCompany, setManualCompany] = useState("");
  const [manualTitle, setManualTitle] = useState("");
  const [manualLocation, setManualLocation] = useState("");
  const [ingesting, setIngesting] = useState(false);

  // Recent Sessions search, filter & pagination (handles 40-100+ sessions cleanly)
  const [sessionSearch, setSessionSearch] = useState("");
  const [sessionFilterWindow, setSessionFilterWindow] = useState<string>("all");
  const [onlyWithJobs, setOnlyWithJobs] = useState(false);
  const [pageSize, setPageSize] = useState<number>(8);
  const [pageIdx, setPageIdx] = useState<number>(0);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    void api.getLocations().then(setLocCatalog).catch(() => {});
  }, []);

  useEffect(() => {
    if (!config) return;
    setFreshness(config.values.posted_within_default || "24h");
    if (!initializedFiltersRef.current) {
      const defaultRoles =
        config.values.target_role_tracks.length > 0
          ? [...config.values.target_role_tracks]
          : roleTracks.map((t) => t.id);
      setSelectedRoleTracks(defaultRoles);
      const srcKeys = (config.values.scraper_sources || []).map((s) => `src:${s}`);
      const boardKeys = (config.values.company_boards || []).map((b) => `board:${b}`);
      setSelectedSourceKeys([...srcKeys, ...boardKeys]);
      const cfgLocs = config.values.target_locations || [];
      setSelectedLocations(cfgLocs.length > 0 ? [...cfgLocs] : ["ALL_US"]);
      initializedFiltersRef.current = true;
    }
  }, [config, roleTracks]);

  useEffect(() => {
    if (activeSessionId != null && expandedSessionId == null && sessions.length > 0) {
      setExpandedSessionId(activeSessionId);
    }
  }, [activeSessionId, sessions.length]);

  const loadJobsForSession = useCallback(async (sessId: number) => {
    setLoadingJobsFor(sessId);
    try {
      const [allJobs, filteredList] = await Promise.all([
        api.listJobs(sessId, true),
        api.listSessionFilteredJobs(sessId),
      ]);
      setJobsBySession((prev) => ({
        ...prev,
        [sessId]: allJobs.filter((j) => j.disposition !== "discarded"),
      }));
      setDiscardedBySession((prev) => ({
        ...prev,
        [sessId]: allJobs.filter((j) => j.disposition === "discarded"),
      }));
      setFilteredBySession((prev) => ({ ...prev, [sessId]: filteredList }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load session jobs.");
    } finally {
      setLoadingJobsFor((cur) => (cur === sessId ? null : cur));
    }
  }, []);

  useEffect(() => {
    if (expandedSessionId != null) {
      void loadJobsForSession(expandedSessionId);
    }
  }, [expandedSessionId, loadJobsForSession]);

  // Poll live scrape progress every 600ms while scraping
  useEffect(() => {
    if (scrapingSessionId == null) return;
    let cancelled = false;
    const poll = async () => {
      try {
        const prog = await api.getScrapeProgress(scrapingSessionId);
        if (cancelled) return;
        setLiveProgress(prog);
        if (prog.status === "completed" || prog.status === "cancelled") {
          setScrapingSessionId(null);
          setStoppingScrape(false);
          if (prog.result) {
            setBatchResult(prog.result);
            const prefix =
              prog.status === "cancelled" ? "Stopped early: scanned" : "Scanned";
            setNotice(
              `${prefix} ${prog.result.scanned_count} postings (${prog.result.posted_within}): kept ${prog.result.saved_count}, dropped ${Math.max(0, prog.result.filtered_count - prog.result.duplicate_skipped_count)} by rules, skipped ${prog.result.duplicate_skipped_count} already seen.`
            );
          } else if (prog.status === "cancelled") {
            setNotice("Scrape stopped early by user.");
          }
          await Promise.all([
            onSessionsChanged(scrapingSessionId),
            loadJobsForSession(scrapingSessionId),
          ]);
        } else if (prog.status === "failed") {
          setScrapingSessionId(null);
          setStoppingScrape(false);
          setError(prog.error || "Batch scrape failed.");
        }
      } catch (err) {
        if (!cancelled) {
          setScrapingSessionId(null);
          setStoppingScrape(false);
          setError(err instanceof Error ? err.message : "Lost connection polling scrape status.");
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), 600);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [scrapingSessionId, onSessionsChanged, loadJobsForSession]);

  const trackName = useCallback(
    (id: string) => roleTracks.find((t) => t.id === id)?.display_name || id,
    [roleTracks]
  );

  const allRoleTrackIds = useMemo(() => roleTracks.map((t) => t.id), [roleTracks]);

  const configDefaultRoleIds = useMemo(
    () => config?.values.target_role_tracks ?? [],
    [config?.values.target_role_tracks]
  );

  const roleYoeLabel = useCallback((t: RoleTrackConfig): string => {
    if (t.typical_yoe_label) return t.typical_yoe_label;
    if (t.target_yoe_range && t.target_yoe_range.length >= 2) {
      return `${t.target_yoe_range[0]}–${t.target_yoe_range[1]} yrs`;
    }
    return "";
  }, []);

  const roleGroups: DropdownOptionGroup[] = useMemo(() => {
    const toItem = (t: RoleTrackConfig) => ({
      value: t.id,
      label: t.display_name,
      badge: roleYoeLabel(t) || undefined,
      subtitle: (
        t.company_examples?.length ? t.company_examples.slice(0, 4) : t.aliases.slice(0, 3)
      ).join(" · "),
      searchText: [t.id, t.description, ...t.aliases, ...(t.company_examples ?? [])].join(" "),
    });

    const configured = roleTracks.filter((t) => configDefaultRoleIds.includes(t.id));
    const remaining = roleTracks.filter((t) => !configDefaultRoleIds.includes(t.id));

    const groups: DropdownOptionGroup[] = [];
    if (configured.length > 0) {
      groups.push({ title: "Config Default Roles", items: configured.map(toItem) });
    }
    const levels = remaining.filter((t) => t.category === "swe_levels");
    if (levels.length > 0) {
      groups.push({
        title: "Company Engineering Levels (With Typical YoE)",
        items: levels.map(toItem),
      });
    }
    const aiData = remaining.filter((t) => t.category === "ai_data");
    if (aiData.length > 0) {
      groups.push({ title: "AI, Machine Learning & Data", items: aiData.map(toItem) });
    }
    const specialties = remaining.filter(
      (t) => t.category !== "swe_levels" && t.category !== "ai_data"
    );
    if (specialties.length > 0) {
      groups.push({
        title: "Backend, Product, Startup, Field & Cloud",
        items: specialties.map(toItem),
      });
    }
    return groups.length > 0
      ? groups
      : [{ title: "Available Role Tracks", items: roleTracks.map(toItem) }];
  }, [roleTracks, configDefaultRoleIds, roleYoeLabel]);

  const roleSummary = useMemo(() => {
    if (selectedRoleTracks.length === 0) return "Select target roles...";
    if (roleTracks.length > 0 && selectedRoleTracks.length === roleTracks.length) {
      return `All Roles (${selectedRoleTracks.length})`;
    }
    if (selectedRoleTracks.length === 1) {
      const tr = roleTracks.find((t) => t.id === selectedRoleTracks[0]);
      const yoe = tr ? roleYoeLabel(tr) : "";
      return yoe ? `${trackName(selectedRoleTracks[0])} (${yoe})` : trackName(selectedRoleTracks[0]);
    }
    if (selectedRoleTracks.length === 2) {
      return selectedRoleTracks.map(trackName).join(", ");
    }
    return `${selectedRoleTracks.length} roles (${trackName(selectedRoleTracks[0])}...)`;
  }, [selectedRoleTracks, roleTracks, trackName, roleYoeLabel]);

  // Source & Board dropdown options
  const sourceGroups: DropdownOptionGroup[] = useMemo(() => {
    const platforms = ["linkedin", "greenhouse", "ashby", "lever"].map((s) => ({
      value: `src:${s}`,
      label: SOURCE_LABELS[s] || s,
    }));
    const boards = (config?.values.company_boards ?? []).map((b) => ({
      value: `board:${b}`,
      label: formatBoardLabel(b),
      badge: b.split(":", 1)[0],
    }));
    return boards.length > 0
      ? [
          { title: "Top Recruiting Sources", items: platforms },
          { title: "Company ATS Boards", items: boards },
        ]
      : [{ title: "Top Recruiting Sources", items: platforms }];
  }, [config?.values.company_boards]);

  const allSourceOptionKeys = useMemo(
    () => sourceGroups.flatMap((g) => g.items.map((item) => item.value)),
    [sourceGroups]
  );

  const top4OptionKeys = useMemo(
    () => [
      ...["linkedin", "greenhouse", "ashby", "lever"].map((s) => `src:${s}`),
      ...(config?.values.company_boards ?? []).map((b) => `board:${b}`),
    ],
    [config?.values.company_boards]
  );

  const configDefaultSourceKeys = useMemo(
    () => [
      ...(config?.values.scraper_sources ?? []).map((s) => `src:${s}`),
      ...(config?.values.company_boards ?? []).map((b) => `board:${b}`),
    ],
    [config?.values.scraper_sources, config?.values.company_boards]
  );

  const sourceSummary = useMemo(() => {
    const activeSources = selectedSourceKeys
      .filter((k) => k.startsWith("src:"))
      .map((k) => k.slice(4));
    const boardCount = selectedSourceKeys.filter((k) => k.startsWith("board:")).length;
    if (activeSources.length === 0 && boardCount === 0) return "Select sources...";
    if (activeSources.length === 1 && activeSources[0] === "linkedin" && boardCount === 0) {
      return "LinkedIn Only";
    }
    if (
      activeSources.length === 4 &&
      ["linkedin", "greenhouse", "ashby", "lever"].every((s) => activeSources.includes(s))
    ) {
      return `Top 4 (${boardCount} boards)`;
    }
    return `${activeSources.map((s) => formatSourceLabel(s)).join(", ")} (${boardCount} boards)`;
  }, [selectedSourceKeys]);

  // US Cities dropdown options (Top 20 pinned at top, All US cities below)
  const locationGroups: DropdownOptionGroup[] = useMemo(() => {
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
    const groups: DropdownOptionGroup[] = [
      {
        title: "Top 20 US Tech Hubs",
        items: [
          { value: "ALL_US", label: "All US Tech Cities (Any US Metro / Remote)", badge: "All US" },
          ...top20.map((city) => ({ value: city, label: city })),
        ],
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

  const handleLocationDropdownChange = (next: string[]) => {
    const hadAllUs = selectedLocations.includes("ALL_US");
    const hasAllUs = next.includes("ALL_US");
    if (!hadAllUs && hasAllUs) {
      setSelectedLocations(["ALL_US"]);
    } else if (hadAllUs && hasAllUs && next.length > 1) {
      setSelectedLocations(next.filter((x) => x !== "ALL_US"));
    } else {
      setSelectedLocations(next);
    }
  };

  const locationSummary = useMemo(() => {
    if (selectedLocations.includes("ALL_US") || selectedLocations.length === 0) {
      return "United States (US Only · All Cities & Remote)";
    }
    if (selectedLocations.length <= 2) return selectedLocations.join(", ");
    return `${selectedLocations.length} US cities (${selectedLocations.slice(0, 2).join(", ")}...)`;
  }, [selectedLocations]);

  const ensureSessionId = async (): Promise<number> => {
    if (newSessionName.trim()) {
      const created = await api.createSession(newSessionName.trim(), freshness);
      setNewSessionName("");
      await onSessionsChanged(created.id);
      onSelectSession(created.id);
      setExpandedSessionId(created.id);
      return created.id;
    }
    if (activeSessionId != null) return activeSessionId;
    const created = await api.createSession(newSessionName.trim(), freshness);
    await onSessionsChanged(created.id);
    onSelectSession(created.id);
    setExpandedSessionId(created.id);
    return created.id;
  };

  const handleCreateSession = async () => {
    setError(null);
    setNotice(null);
    try {
      const created = await api.createSession(newSessionName.trim(), freshness);
      setNewSessionName("");
      await onSessionsChanged(created.id);
      onSelectSession(created.id);
      setExpandedSessionId(created.id);
      setPageIdx(0);
      setNotice(`Created ${created.name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create session.");
    }
  };

  const handleStartScrape = async () => {
    if (selectedRoleTracks.length === 0) {
      setError("Select at least one target role before scraping.");
      return;
    }
    const chosenSources = selectedSourceKeys
      .filter((k) => k.startsWith("src:"))
      .map((k) => k.slice(4));
    if (chosenSources.length === 0) {
      setError("Select at least one recruiting source before scraping.");
      return;
    }
    const chosenBoards = selectedSourceKeys
      .filter((k) => k.startsWith("board:"))
      .map((k) => k.slice(6));

    setError(null);
    setNotice(null);
    setBatchResult(null);
    try {
      // Each scrape is considered a brand new session
      const dateStr = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric" });
      const nextSessionNum = sessions.length + 1;
      const defaultName = `Session ${nextSessionNum} (${dateStr} • ${freshness})`;
      const sessionName = newSessionName.trim() || defaultName;
      const created = await api.createSession(sessionName, freshness);
      setNewSessionName("");
      await onSessionsChanged(created.id);
      onSelectSession(created.id);
      setExpandedSessionId(created.id);
      const targetSessionId = created.id;

      const initialProg = await api.startSessionScrape(targetSessionId, {
        posted_within: freshness,
        role_tracks: selectedRoleTracks,
        sources: chosenSources,
        company_boards: chosenBoards,
        locations: selectedLocations.length > 0 ? selectedLocations : ["ALL_US"],
      });
      setLiveProgress(initialProg);
      setScrapingSessionId(targetSessionId);
      setStoppingScrape(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start scrape.");
    }
  };

  const handleStopScrape = async () => {
    if (scrapingSessionId == null || stoppingScrape) return;
    setStoppingScrape(true);
    setError(null);
    try {
      const prog = await api.stopSessionScrape(scrapingSessionId);
      setLiveProgress(prog);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to request stop.");
      setStoppingScrape(false);
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
      await Promise.all([onSessionsChanged(targetSessionId), loadJobsForSession(targetSessionId)]);
      setExpandedSessionId(targetSessionId);
      setNotice(`Added ${created.analysis.title} at ${created.analysis.company}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add job posting.");
    } finally {
      setIngesting(false);
    }
  };

  // Filtered & paginated sessions for 40-100+ session scale
  const filteredSessions = useMemo(() => {
    const q = sessionSearch.trim().toLowerCase();
    return sessions.filter((s) => {
      if (onlyWithJobs && s.total_jobs === 0) return false;
      if (sessionFilterWindow !== "all" && s.posted_within !== sessionFilterWindow) return false;
      if (q) {
        const hay = [
          s.name,
          s.posted_within,
          ...s.sources_used,
          ...s.locations.map((l) => l.location),
          ...s.roles.map((r) => trackName(r.role_track)),
        ]
          .join(" ")
          .toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [sessions, onlyWithJobs, sessionFilterWindow, sessionSearch, roleTracks]);

  const totalPages = pageSize <= 0 ? 1 : Math.max(1, Math.ceil(filteredSessions.length / pageSize));
  const safePageIdx = Math.min(pageIdx, totalPages - 1);
  const paginatedSessions = useMemo(() => {
    if (pageSize <= 0) return filteredSessions;
    const start = safePageIdx * pageSize;
    return filteredSessions.slice(start, start + pageSize);
  }, [filteredSessions, safePageIdx, pageSize]);

  const isScraping = scrapingSessionId != null && liveProgress?.status === "running";
  const progressPct = useMemo(() => {
    if (!liveProgress) return 0;
    if (liveProgress.phase === "Completed") return 100;
    if (liveProgress.scanned_count > 0 && liveProgress.phase.includes("Filtering")) {
      return Math.min(
        98,
        45 + Math.round((liveProgress.processed_count / Math.max(1, liveProgress.scanned_count)) * 53)
      );
    }
    if (liveProgress.steps_total > 0) {
      return Math.max(6, Math.round((liveProgress.steps_completed / liveProgress.steps_total) * 45));
    }
    return 10;
  }, [liveProgress]);

  return (
    <div className="stack-md">
      {/* Top Pre-Scrape Control Card */}
      <div className="card stack-md">
        <div className="form-grid-3">
          <div>
            <label>Target Session</label>
            <select
              value={activeSessionId ?? ""}
              onChange={(e) => {
                const nextId = Number(e.target.value);
                onSelectSession(nextId);
                setExpandedSessionId(nextId);
              }}
            >
              {sessions.length === 0 && <option value="">Auto-create Session 1</option>}
              {sessions.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name} ({s.total_jobs} kept)
                </option>
              ))}
            </select>
          </div>

          <div>
            <label>Posted Within</label>
            <select value={freshness} onChange={(e) => setFreshness(e.target.value)}>
              {FRESHNESS_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label>New Session Name (optional)</label>
            <div className="row-wrap" style={{ flexWrap: "nowrap" }}>
              <input
                value={newSessionName}
                onChange={(e) => setNewSessionName(e.target.value)}
                placeholder="e.g. Evening AI Run"
              />
              <button type="button" className="btn" onClick={() => void handleCreateSession()}>
                + New
              </button>
            </div>
          </div>
        </div>

        {/* Pre-scrape Primary US Location, Target Roles & Recruiting Sources Filters */}
        <div className="form-grid-3">
          <MultiSelectCheckboxDropdown
            label="Location (Primary · US Only Default)"
            summaryText={locationSummary}
            groups={locationGroups}
            selected={selectedLocations}
            onChange={handleLocationDropdownChange}
            searchPlaceholder="Search US city or state..."
            disabled={isScraping}
            quickActions={[
              {
                label: "United States (Default)",
                active:
                  selectedLocations.includes("ALL_US") || selectedLocations.length === 0,
                onClick: () => setSelectedLocations(["ALL_US"]),
              },
              {
                label: "Top 20 Cities",
                onClick: () => setSelectedLocations([...(locCatalog?.top_20 ?? [])]),
              },
              {
                label: "Config Default",
                onClick: () => {
                  const cfgLocs = config?.values.target_locations ?? [];
                  setSelectedLocations(cfgLocs.length > 0 ? [...cfgLocs] : ["ALL_US"]);
                },
              },
              {
                label: "Reset US Only",
                onClick: () => setSelectedLocations(["ALL_US"]),
              },
            ]}
          />

          <MultiSelectCheckboxDropdown
            label="Target Roles (With Typical YoE)"
            summaryText={roleSummary}
            groups={roleGroups}
            selected={selectedRoleTracks}
            onChange={setSelectedRoleTracks}
            searchPlaceholder="Search role, level (L5/L6/MTS), or company..."
            disabled={isScraping}
            quickActions={[
              {
                label: "All Roles",
                active:
                  allRoleTrackIds.length > 0 &&
                  allRoleTrackIds.every((id) => selectedRoleTracks.includes(id)),
                onClick: () => setSelectedRoleTracks(allRoleTrackIds),
              },
              {
                label: "Mid + Senior (2–8 yrs)",
                onClick: () =>
                  setSelectedRoleTracks(
                    allRoleTrackIds.filter((id) => id === "mid_swe" || id === "senior_swe")
                  ),
              },
              {
                label: "Staff / Principal (8+ yrs)",
                onClick: () =>
                  setSelectedRoleTracks(
                    allRoleTrackIds.filter((id) => id === "staff_swe" || id === "principal_swe")
                  ),
              },
              {
                label: "AI & Data",
                onClick: () =>
                  setSelectedRoleTracks(
                    roleTracks.filter((t) => t.category === "ai_data").map((t) => t.id)
                  ),
              },
              {
                label: "Config Default",
                active:
                  configDefaultRoleIds.length > 0 &&
                  configDefaultRoleIds.length === selectedRoleTracks.length &&
                  configDefaultRoleIds.every((id) => selectedRoleTracks.includes(id)),
                onClick: () => setSelectedRoleTracks([...configDefaultRoleIds]),
              },
              {
                label: "Clear",
                active: selectedRoleTracks.length === 0,
                onClick: () => setSelectedRoleTracks([]),
              },
            ]}
          />

          <MultiSelectCheckboxDropdown
            label="Recruiting Websites & Boards"
            summaryText={sourceSummary}
            groups={sourceGroups}
            selected={selectedSourceKeys}
            onChange={setSelectedSourceKeys}
            searchPlaceholder="Filter sources or company boards..."
            disabled={isScraping}
            quickActions={[
              {
                label: "Top 4",
                active:
                  top4OptionKeys.length > 0 &&
                  top4OptionKeys.every((k) => selectedSourceKeys.includes(k)),
                onClick: () => setSelectedSourceKeys(top4OptionKeys),
              },
              {
                label: "LinkedIn Only",
                active:
                  selectedSourceKeys.length === 1 && selectedSourceKeys[0] === "src:linkedin",
                onClick: () => setSelectedSourceKeys(["src:linkedin"]),
              },
              {
                label: "All",
                active:
                  allSourceOptionKeys.length > 0 &&
                  allSourceOptionKeys.every((k) => selectedSourceKeys.includes(k)),
                onClick: () => setSelectedSourceKeys(allSourceOptionKeys),
              },
              {
                label: "Clear",
                active: selectedSourceKeys.length === 0,
                onClick: () => setSelectedSourceKeys([]),
              },
              {
                label: "Config Default",
                onClick: () => setSelectedSourceKeys(configDefaultSourceKeys),
              },
            ]}
          />
        </div>

        <div className="row-between">
          {config ? (
            <div className="row-wrap small-note">
              <span>
                Location Scope: <strong>{locationSummary}</strong>
              </span>
              <span>&middot;</span>
              <span>
                Roles:{" "}
                <strong>
                  {selectedRoleTracks.length > 0
                    ? selectedRoleTracks.map(trackName).join(", ")
                    : "None selected"}
                </strong>
              </span>
              <span>&middot;</span>
              <span>
                Auth: <strong>{config.values.work_authorization.toUpperCase()}</strong>
              </span>
              <span>&middot;</span>
              <span className="pill">US Focus Active</span>
            </div>
          ) : (
            <span />
          )}

          <div className="row-wrap">
            <button
              type="button"
              className="btn"
              onClick={() => setShowManualDrawer((v) => !v)}
            >
              {showManualDrawer ? "Close URL/JD" : "+ Add URL / Paste JD"}
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleStartScrape()}
              disabled={isScraping}
            >
              {isScraping ? "Scraping Live..." : "Scrape Target Roles"}
            </button>
          </div>
        </div>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {notice && <div className="alert alert-success">{notice}</div>}

      {/* Real-Time Scrape Progress Banner */}
      {liveProgress && liveProgress.status === "running" && (
        <div className="progress-banner">
          <div className="row-between">
            <div className="row-wrap">
              <span className="pill pill-blue">{liveProgress.phase || "Running"}</span>
              <strong>{liveProgress.current_source || "Working..."}</strong>
            </div>
            <div className="row-wrap">
              <span className="mono small-note">
                Step {liveProgress.steps_completed} / {liveProgress.steps_total || 1} &middot;{" "}
                {progressPct}%
              </span>
              <button
                type="button"
                className="btn btn-sm btn-danger-ghost"
                onClick={() => void handleStopScrape()}
                disabled={stoppingScrape}
              >
                {stoppingScrape ? "Stopping..." : "Stop Scrape"}
              </button>
            </div>
          </div>
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progressPct}%` }} />
          </div>
          <div className="row-wrap">
            <span className="pill">Scanned: {liveProgress.scanned_count}</span>
            <span className="pill">Analyzed: {liveProgress.processed_count}</span>
            <span className="pill pill-green">Saved: {liveProgress.saved_count}</span>
            <span className="pill pill-amber">
              Filtered (Rules):{" "}
              {Math.max(0, liveProgress.filtered_count - liveProgress.duplicate_skipped_count)}
            </span>
            <span className="pill">Seen / Skipped: {liveProgress.duplicate_skipped_count}</span>
            {Object.entries(liveProgress.filter_breakdown || {}).map(([k, v]) => (
              <span key={k} className="pill">
                {k}: {v}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Post-Scrape Summary Banner */}
      {batchResult && !isScraping && (
        <div className="card-elevated stack-sm">
          <div className="row-between">
            <div className="row-wrap">
              <strong>Latest Scrape Summary ({batchResult.posted_within})</strong>
              {batchResult.cancelled && <span className="pill pill-amber">Stopped Early</span>}
            </div>
            <div className="row-wrap">
              <span className="pill">Scanned: {batchResult.scanned_count}</span>
              <span className="pill pill-green">Saved: {batchResult.saved_count}</span>
              <span className="pill pill-amber">
                Filtered (Rules):{" "}
                {Math.max(0, batchResult.filtered_count - batchResult.duplicate_skipped_count)}
              </span>
              <span className="pill">Seen / Skipped: {batchResult.duplicate_skipped_count}</span>
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
          <h3 style={{ margin: 0, fontSize: 15 }}>Add Single Job</h3>
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
            <AutoGrowTextarea
              minHeight={90}
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              placeholder="Paste the full job description text here if behind login/anti-bot wall..."
            />
          </div>
          <div className="row-between">
            <span className="small-note">Role track is automatically inferred from title &amp; keywords.</span>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => void handleManualIngest()}
              disabled={ingesting}
            >
              {ingesting ? "Analyzing..." : "Analyze & Add to Session"}
            </button>
          </div>
        </div>
      )}

      {/* Scalable Recent Sessions Browser (Horizontal Placards + Drop-Down Finalized Jobs) */}
      <div className="card stack-md">
        <div className="row-between">
          <div>
            <h3 style={{ margin: 0, fontSize: 16 }}>
              Recent Sessions ({filteredSessions.length}
              {filteredSessions.length !== sessions.length ? ` / ${sessions.length}` : ""})
            </h3>
            <div className="small-note">
              Click any session placard to drop down its finalized jobs, per-job skills gap, and tailoring tools.
            </div>
          </div>

          <div className="row-wrap">
            <div style={{ minWidth: 220 }}>
              <input
                value={sessionSearch}
                onChange={(e) => {
                  setSessionSearch(e.target.value);
                  setPageIdx(0);
                }}
                placeholder="Search session, city, role, source..."
              />
            </div>
            <button
              type="button"
              className={`chip ${onlyWithJobs ? "selected" : ""}`}
              onClick={() => {
                setOnlyWithJobs((v) => !v);
                setPageIdx(0);
              }}
            >
              Has Kept Jobs
            </button>
            <select
              style={{ width: "auto" }}
              value={sessionFilterWindow}
              onChange={(e) => {
                setSessionFilterWindow(e.target.value);
                setPageIdx(0);
              }}
            >
              <option value="all">All Windows</option>
              <option value="1h">1h Window</option>
              <option value="12h">12h Window</option>
              <option value="24h">24h Window</option>
              <option value="7d">7d Window</option>
            </select>
            <select
              style={{ width: "auto" }}
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPageIdx(0);
              }}
            >
              <option value={5}>Show 5 / page</option>
              <option value={8}>Show 8 / page</option>
              <option value={20}>Show 20 / page</option>
              <option value={0}>Show All</option>
            </select>
          </div>
        </div>

        {paginatedSessions.length === 0 ? (
          <div className="muted" style={{ padding: "18px 4px" }}>
            {sessions.length === 0
              ? "No scrape sessions yet. Click Scrape Target Roles above to start Session 1."
              : "No sessions match your search or window filter."}
          </div>
        ) : (
          <div className="stack-sm">
            {paginatedSessions.map((sess) => {
              const isExpanded = expandedSessionId === sess.id;
              const isSelected = activeSessionId === sess.id;
              const appliedCount = sess.status_counts?.applied || 0;
              const tailoredCount = sess.status_counts?.resume_created || 0;

              return (
                <div
                  key={sess.id}
                  className={`session-placard ${isExpanded || isSelected ? "active" : ""}`}
                >
                  <button
                    type="button"
                    className="session-placard-header"
                    onClick={() => {
                      onSelectSession(sess.id);
                      setExpandedSessionId(isExpanded ? null : sess.id);
                    }}
                  >
                    <div className="row-between" style={{ width: "100%" }}>
                      <div className="row-wrap">
                        <span className="mono" style={{ color: "var(--accent-blue)", fontWeight: 700 }}>
                          {isExpanded ? "▾" : "▸"}
                        </span>
                        <strong style={{ fontSize: 15 }}>{sess.name}</strong>
                        <span className="pill">{formatEasternDateTime(sess.created_at)}</span>
                        <span className="pill pill-blue">{sess.posted_within}</span>
                        {sess.sources_used.map((src) => (
                          <span key={src} className="pill">
                            {formatSourceLabel(src)}
                          </span>
                        ))}
                      </div>

                      <div className="session-metrics-strip">
                        <span className="session-metric-chip">
                          Saved <strong>{sess.total_jobs}</strong>
                        </span>
                        <span className="session-metric-chip">
                          Scanned <strong>{sess.scanned_count}</strong>
                        </span>
                        <span className="session-metric-chip">
                          Filtered (Rules){" "}
                          <strong>
                            {Math.max(0, sess.filtered_count - (sess.seen_skipped_count || 0))}
                          </strong>
                        </span>
                        <span className="session-metric-chip">
                          Seen / Skipped <strong>{sess.seen_skipped_count || 0}</strong>
                        </span>
                        {sess.discarded_count > 0 && (
                          <span className="session-metric-chip">
                            Discarded <strong>{sess.discarded_count}</strong>
                          </span>
                        )}
                        {tailoredCount > 0 && (
                          <span className="pill pill-blue">{tailoredCount} Tailored</span>
                        )}
                        {appliedCount > 0 && (
                          <span className="pill pill-green">{appliedCount} Applied</span>
                        )}
                      </div>
                    </div>

                    {(sess.locations.length > 0 || sess.roles.length > 0) && (
                      <div className="row-wrap">
                        {sess.roles.slice(0, 4).map((r) => (
                          <span key={r.role_track} className="pill">
                            {trackName(r.role_track)}: {r.count}
                          </span>
                        ))}
                        {sess.locations.slice(0, 4).map((l) => (
                          <span key={l.location} className="small-note">
                            {l.location} ({l.count})
                          </span>
                        ))}
                      </div>
                    )}
                  </button>

                  {isExpanded && (
                    <div className="session-dropdown-body">
                      <SessionJobsWorkspace
                        session={sess}
                        config={config}
                        jobs={jobsBySession[sess.id] ?? []}
                        discardedJobs={discardedBySession[sess.id] ?? []}
                        filteredItems={filteredBySession[sess.id] ?? []}
                        loadingJobs={loadingJobsFor === sess.id}
                        roleTracks={roleTracks}
                        resumeState={resumeState}
                        onResumesChanged={onResumesChanged}
                        onJobsUpdated={async () => {
                          await Promise.all([
                            loadJobsForSession(sess.id),
                            onSessionsChanged(sess.id),
                          ]);
                        }}
                        onNavigateTab={onNavigateTab}
                        viewportMode={viewportMode}
                        onChangeViewportMode={onChangeViewportMode}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {totalPages > 1 && (
          <div className="row-between">
            <span className="small-note">
              Page {safePageIdx + 1} of {totalPages} &middot; {filteredSessions.length} sessions
            </span>
            <div className="row-wrap">
              <button
                type="button"
                className="btn btn-sm"
                disabled={safePageIdx === 0}
                onClick={() => setPageIdx((p) => Math.max(0, p - 1))}
              >
                Previous
              </button>
              <button
                type="button"
                className="btn btn-sm"
                disabled={safePageIdx >= totalPages - 1}
                onClick={() => setPageIdx((p) => Math.min(totalPages - 1, p + 1))}
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
