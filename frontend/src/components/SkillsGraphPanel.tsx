import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { formatSkillName } from "../constants/tailoring";
import type {
  RoleTrackConfig,
  ScrapeSessionSummary,
  SkillsGraphDomainSummary,
  SkillsGraphJobNode,
  SkillsGraphResponse,
  SkillsGraphSkillNode,
} from "../types";

interface SkillsGraphPanelProps {
  sessions: ScrapeSessionSummary[];
  selectedSessionId: number | null;
  roleTracks: RoleTrackConfig[];
  onRoleTrackUpdated?: () => Promise<void>;
}

type SelectedNodeRef =
  | { kind: "domain"; domain: SkillsGraphDomainSummary }
  | { kind: "job"; job: SkillsGraphJobNode }
  | { kind: "skill"; skill: SkillsGraphSkillNode }
  | null;

export function SkillsGraphPanel({
  sessions,
  selectedSessionId,
  roleTracks,
  onRoleTrackUpdated,
}: SkillsGraphPanelProps) {
  const [scopeSessionId, setScopeSessionId] = useState<number | null>(selectedSessionId);
  const [graph, setGraph] = useState<SkillsGraphResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [syncingTrack, setSyncingTrack] = useState(false);

  const [domainFilter, setDomainFilter] = useState<string>("all");
  const [coverageFilter, setCoverageFilter] = useState<"all" | "missing" | "covered">("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedNode, setSelectedNode] = useState<SelectedNodeRef>(null);

  const loadGraph = useCallback(async (sid: number | null) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getSkillsGraph(sid);
      setGraph(data);
      if (data.domains.length > 0) {
        setSelectedNode({ kind: "domain", domain: data.domains[0] });
      } else {
        setSelectedNode(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to build skills graph.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadGraph(scopeSessionId);
  }, [scopeSessionId, loadGraph]);

  const filteredJobs = useMemo(() => {
    if (!graph) return [];
    const q = searchQuery.trim().toLowerCase();
    return graph.jobs.filter((j) => {
      if (domainFilter !== "all" && j.domain !== domainFilter) return false;
      if (q) {
        const hay = `${j.company} ${j.title} ${j.domain} ${j.role_label} ${j.skills.join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [graph, domainFilter, searchQuery]);

  const visibleJobIds = useMemo(() => new Set(filteredJobs.map((j) => j.job_id)), [filteredJobs]);

  const filteredSkills = useMemo(() => {
    if (!graph) return [];
    const q = searchQuery.trim().toLowerCase();
    return graph.skills.filter((s) => {
      if (coverageFilter === "missing" && s.is_covered) return false;
      if (coverageFilter === "covered" && !s.is_covered) return false;
      if (domainFilter !== "all" && !s.domains.includes(domainFilter)) return false;
      if (filteredJobs.length > 0 && !s.job_ids.some((id) => visibleJobIds.has(id))) {
        return false;
      }
      if (q) {
        const hay = `${s.keyword} ${s.domains.join(" ")} ${s.companies.join(" ")}`.toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }, [graph, coverageFilter, domainFilter, filteredJobs.length, visibleJobIds, searchQuery]);

  const svgLayout = useMemo(() => {
    const jobsSlice = filteredJobs.slice(0, 14);
    const domainList = Array.from(new Set(jobsSlice.map((j) => j.domain))).slice(0, 8);
    const skillsSlice = filteredSkills.slice(0, 20);

    const width = 1180;
    const maxCount = Math.max(jobsSlice.length, domainList.length, skillsSlice.length, 4);
    const height = Math.max(460, maxCount * 38 + 70);

    const distributeY = (idx: number, total: number) => {
      if (total <= 1) return height / 2;
      const pad = 42;
      const span = height - pad * 2;
      return pad + (idx / (total - 1)) * span;
    };

    const jobPos = new Map<string, { x: number; y: number; item: SkillsGraphJobNode }>();
    jobsSlice.forEach((j, idx) => {
      jobPos.set(j.id, { x: 24, y: distributeY(idx, jobsSlice.length), item: j });
    });

    const domainPos = new Map<string, { x: number; y: number; label: string }>();
    domainList.forEach((dom, idx) => {
      domainPos.set(dom, { x: 460, y: distributeY(idx, domainList.length), label: dom });
    });

    const skillPos = new Map<string, { x: number; y: number; item: SkillsGraphSkillNode }>();
    skillsSlice.forEach((sk, idx) => {
      skillPos.set(sk.id, { x: 880, y: distributeY(idx, skillsSlice.length), item: sk });
    });

    return { width, height, jobsSlice, domainList, skillsSlice, jobPos, domainPos, skillPos };
  }, [filteredJobs, filteredSkills]);

  const highlightedIds = useMemo(() => {
    const set = new Set<string>();
    if (!selectedNode || !graph) return set;
    if (selectedNode.kind === "domain") {
      const dom = selectedNode.domain.domain;
      set.add(`domain:${dom}`);
      for (const j of graph.jobs) {
        if (j.domain === dom) set.add(j.id);
      }
      for (const s of graph.skills) {
        if (s.domains.includes(dom)) set.add(s.id);
      }
    } else if (selectedNode.kind === "job") {
      const j = selectedNode.job;
      set.add(j.id);
      set.add(`domain:${j.domain}`);
      for (const s of graph.skills) {
        if (s.job_ids.includes(j.job_id)) set.add(s.id);
      }
    } else if (selectedNode.kind === "skill") {
      const s = selectedNode.skill;
      set.add(s.id);
      for (const dom of s.domains) set.add(`domain:${dom}`);
      for (const jid of s.job_ids) set.add(`job:${jid}`);
    }
    return set;
  }, [selectedNode, graph]);

  const handleSyncMissingToTrack = async (trackId: string, missingTerms: string[]) => {
    const targetTrack = roleTracks.find((t) => t.id === trackId);
    if (!targetTrack || missingTerms.length === 0) return;
    setSyncingTrack(true);
    setError(null);
    setNotice(null);
    try {
      const currentSys = targetTrack.keywords.important_systems ?? [];
      const existingSet = new Set(
        [
          ...(targetTrack.keywords.core_must_have ?? []),
          ...currentSys,
          ...(targetTrack.keywords.bonus_nice_to_have ?? []),
        ].map((k) => k.toLowerCase())
      );
      const additions = missingTerms.filter((t) => !existingSet.has(t.toLowerCase())).slice(0, 8);
      if (additions.length === 0) {
        setNotice(`All selected skills are already tracked inside '${targetTrack.display_name}'.`);
        return;
      }
      await api.updateRoleTrack(trackId, {
        keywords: {
          ...targetTrack.keywords,
          important_systems: [...currentSys, ...additions],
        },
      });
      if (onRoleTrackUpdated) {
        await onRoleTrackUpdated();
      }
      setNotice(
        `Added ${additions.length} discovered skill(s) (${additions.join(", ")}) to '${targetTrack.display_name}' config track.`
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update role track config.");
    } finally {
      setSyncingTrack(false);
    }
  };

  return (
    <div className="stack-lg">
      <div className="card stack-md">
        <div className="row-between">
          <div>
            <h2 style={{ margin: 0, fontSize: 20 }}>Skills Graph</h2>
            <div className="small-note">
              Visualizes companies, roles, engineering domains, and demanded skills extracted from scraped sessions — click any node to inspect or sync gaps to Config.
            </div>
          </div>

          <div className="row-wrap">
            <select
              style={{ width: 230 }}
              value={scopeSessionId == null ? "all" : String(scopeSessionId)}
              onChange={(e) =>
                setScopeSessionId(e.target.value === "all" ? null : Number(e.target.value))
              }
            >
              <option value="all">All Sessions</option>
              {sessions.map((s) => (
                <option key={s.id} value={String(s.id)}>
                  {s.name} ({s.total_jobs})
                </option>
              ))}
            </select>

            <button
              type="button"
              className="btn btn-sm"
              onClick={() => void loadGraph(scopeSessionId)}
              disabled={loading}
            >
              {loading ? "Building..." : "Refresh Graph"}
            </button>
          </div>
        </div>

        {error && <div className="alert alert-error">{error}</div>}
        {notice && <div className="alert alert-success">{notice}</div>}

        {graph && (
          <>
            <div className="stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: 12, margin: "12px 0 16px" }}>
              <div className="stat-box" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 16px" }}>
                <span className="stat-label">Active Postings Mapped</span>
                <span className="stat-value">{graph.total_jobs}</span>
              </div>
              <div className="stat-box" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 16px" }}>
                <span className="stat-label">Engineering Domains</span>
                <span className="stat-value" style={{ color: "var(--accent-blue)" }}>
                  {graph.domains.length}
                </span>
              </div>
              <div className="stat-box" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 16px" }}>
                <span className="stat-label">Required Skills Extracted</span>
                <span className="stat-value">{graph.total_skills}</span>
              </div>
              <div className="stat-box" style={{ display: "flex", flexDirection: "column", gap: 6, padding: "12px 16px" }}>
                <span className="stat-label">Resume Coverage vs Gaps</span>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 2 }}>
                  <span className="stat-value" style={{ color: "var(--accent-green)" }}>
                    {graph.covered_skills}{" "}
                    <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-secondary)" }}>
                      covered
                    </span>
                  </span>
                  <span style={{ color: "var(--border-strong)", fontSize: 16 }}>/</span>
                  <span className="stat-value" style={{ color: "var(--accent-amber)" }}>
                    {graph.missing_skills}{" "}
                    <span style={{ fontSize: 13, fontWeight: 500, color: "var(--text-secondary)" }}>
                      missing
                    </span>
                  </span>
                </div>
              </div>
            </div>

            <div className="session-filter-bar">
              <select
                value={domainFilter}
                onChange={(e) => setDomainFilter(e.target.value)}
                aria-label="Filter graph by domain"
              >
                <option value="all">All Domains ({graph.domains.length})</option>
                {graph.domains.map((d) => (
                  <option key={d.domain} value={d.domain}>
                    {d.domain} ({d.job_count})
                  </option>
                ))}
              </select>

              <select
                value={coverageFilter}
                onChange={(e) => setCoverageFilter(e.target.value as "all" | "missing" | "covered")}
                aria-label="Filter skills by resume coverage"
              >
                <option value="all">All Skills ({graph.total_skills})</option>
                <option value="missing">Missing From Base Resume ({graph.missing_skills})</option>
                <option value="covered">Covered By Base Resume ({graph.covered_skills})</option>
              </select>

              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search company, role, domain, or skill..."
              />
            </div>

            {graph.total_jobs === 0 ? (
              <div className="alert">
                No active scraped postings found in this scope yet. Run a Scrape Session first.
              </div>
            ) : (
              <div className="stack-md">
                {/* Top Inspector & Config Sync Banner (Full Width Across Top) */}
                <div className="skills-graph-top-inspector stack-sm">
                  <div className="row-between">
                    <div className="row-wrap" style={{ gap: 8, alignItems: "center" }}>
                      <strong style={{ fontSize: 14 }}>Node Inspector</strong>
                      {selectedNode ? (
                        <span className="small-note">
                          (Click any other node in the graph below to switch focus)
                        </span>
                      ) : (
                        <span className="small-note">
                          (Click any company posting, domain cluster, or skill badge to inspect &amp; sync)
                        </span>
                      )}
                    </div>
                    {selectedNode && (
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setSelectedNode(null)}
                      >
                        Reset Selection
                      </button>
                    )}
                  </div>

                  {!selectedNode ? (
                    <div className="small-note" style={{ color: "var(--text-secondary)" }}>
                      Select any node below to inspect connected postings, required skills, and one-click sync missing skills to your role tracks.
                    </div>
                  ) : selectedNode.kind === "domain" ? (
                    <div className="stack-sm">
                      <div className="row-wrap" style={{ alignItems: "center", gap: 10 }}>
                        <span className="pill pill-blue" style={{ fontSize: 13, fontWeight: 700 }}>
                          Domain: {selectedNode.domain.domain}
                        </span>
                        <span className="small-note">
                          <strong>{selectedNode.domain.job_count}</strong> active postings across{" "}
                          {selectedNode.domain.companies.join(", ")}
                        </span>
                      </div>
                      <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                        <strong style={{ fontSize: 11.5, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                          Target Roles:
                        </strong>
                        {selectedNode.domain.role_tracks.map((rt) => (
                          <span key={rt} className="pill">
                            {rt}
                          </span>
                        ))}
                      </div>
                      <div className="row-wrap" style={{ alignItems: "center", gap: 6 }}>
                        <strong style={{ fontSize: 11.5, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                          Top Skills Demanded:
                        </strong>
                        {selectedNode.domain.top_skills.map((sk) => (
                          <span
                            key={sk}
                            className={`pill ${
                              selectedNode.domain.missing_skills.includes(sk)
                                ? "pill-amber"
                                : "pill-green"
                            }`}
                          >
                            {formatSkillName(sk)}
                          </span>
                        ))}
                      </div>
                      {selectedNode.domain.missing_skills.length > 0 && roleTracks.length > 0 && (
                        <div className="row-wrap" style={{ marginTop: 4, alignItems: "center", gap: 8 }}>
                          <strong style={{ fontSize: 11.5, color: "var(--accent-amber)" }}>
                            Sync Domain Gaps Into Track:
                          </strong>
                          {roleTracks.slice(0, 5).map((rt) => (
                            <button
                              key={rt.id}
                              type="button"
                              className="btn btn-sm"
                              disabled={syncingTrack}
                              onClick={() =>
                                void handleSyncMissingToTrack(
                                  rt.id,
                                  selectedNode.domain.missing_skills
                                )
                              }
                            >
                              + Sync to {rt.display_name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : selectedNode.kind === "job" ? (
                    <div className="stack-sm">
                      <div className="row-wrap" style={{ alignItems: "center", gap: 10 }}>
                        <span className="pill pill-blue">{selectedNode.job.domain}</span>
                        <strong style={{ fontSize: 14 }}>
                          {selectedNode.job.title} — {selectedNode.job.company}
                        </strong>
                        <span className="small-note">
                          {selectedNode.job.role_label} &middot; {selectedNode.job.location} &middot; Match {Math.round(selectedNode.job.relevance_score)}%
                        </span>
                      </div>
                      <div className="row-wrap" style={{ alignItems: "center", gap: 6 }}>
                        <strong style={{ fontSize: 11.5, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                          Extracted Skills:
                        </strong>
                        {selectedNode.job.skills.map((sk) => (
                          <span key={sk} className="pill">
                            {formatSkillName(sk)}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : (
                    <div className="stack-sm">
                      <div className="row-wrap" style={{ alignItems: "center", gap: 10 }}>
                        <strong style={{ fontSize: 15 }}>{formatSkillName(selectedNode.skill.keyword)}</strong>
                        <span
                          className={`pill ${
                            selectedNode.skill.is_covered ? "pill-green" : "pill-amber"
                          }`}
                        >
                          {selectedNode.skill.is_covered ? "Covered on Base Resume" : "Missing Gap"}
                        </span>
                        <span className="small-note">
                          Priority: <strong>{selectedNode.skill.priority_label}</strong> &middot; Demanded in {selectedNode.skill.demand_count} posting(s) ({selectedNode.skill.demand_pct}%)
                        </span>
                      </div>
                      <div className="row-wrap" style={{ alignItems: "center", gap: 6 }}>
                        <strong style={{ fontSize: 11.5, textTransform: "uppercase", color: "var(--text-secondary)" }}>
                          Domains:
                        </strong>
                        <span className="small-note">{selectedNode.skill.domains.join(" • ")}</span>
                        <span className="small-note" style={{ marginLeft: 8 }}>
                          Companies: {selectedNode.skill.companies.join(", ")}
                        </span>
                      </div>
                      {!selectedNode.skill.is_covered && roleTracks.length > 0 && (
                        <div className="row-wrap" style={{ marginTop: 4, alignItems: "center", gap: 8 }}>
                          <strong style={{ fontSize: 11.5, color: "var(--accent-amber)" }}>
                            Quick Track:
                          </strong>
                          {roleTracks.slice(0, 4).map((rt) => (
                            <button
                              key={rt.id}
                              type="button"
                              className="btn btn-sm btn-primary"
                              disabled={syncingTrack}
                              onClick={() =>
                                void handleSyncMissingToTrack(rt.id, [selectedNode.skill.keyword])
                              }
                            >
                              + Add to {rt.display_name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* Interactive Full-Width 3-Column Network Canvas */}
                <div className="skills-graph-fullwidth-canvas stack-sm">
                  <div className="row-between">
                    <strong style={{ fontSize: 13.5 }}>
                      Role &rarr; Domain &rarr; Required Skills
                    </strong>
                    <div className="row-wrap" style={{ fontSize: 11.5 }}>
                      <span className="pill pill-green">Covered Skill</span>
                      <span className="pill pill-amber">Missing Gap</span>
                      <span className="pill pill-blue">Domain Cluster</span>
                    </div>
                  </div>

                  <svg
                    viewBox={`0 0 ${svgLayout.width} ${svgLayout.height}`}
                    style={{ width: "100%", minWidth: 920, height: svgLayout.height }}
                  >
                    {/* Edges: Job -> Domain */}
                    {svgLayout.jobsSlice.map((j) => {
                      const jp = svgLayout.jobPos.get(j.id);
                      const dp = svgLayout.domainPos.get(j.domain);
                      if (!jp || !dp) return null;
                      const active =
                        highlightedIds.size === 0 ||
                        (highlightedIds.has(j.id) && highlightedIds.has(`domain:${j.domain}`));
                      const x1 = jp.x + 280;
                      const y1 = jp.y;
                      const x2 = dp.x;
                      const y2 = dp.y;
                      const mx = (x1 + x2) / 2;
                      return (
                        <path
                          key={`jd-${j.id}-${j.domain}`}
                          d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                          fill="none"
                          stroke={active ? "rgba(10, 132, 255, 0.65)" : "rgba(255,255,255,0.06)"}
                          strokeWidth={active ? 2 : 1}
                        />
                      );
                    })}

                    {/* Edges: Domain -> Skill */}
                    {svgLayout.skillsSlice.map((sk) => {
                      const sp = svgLayout.skillPos.get(sk.id);
                      if (!sp) return null;
                      return sk.domains.map((dom) => {
                        const dp = svgLayout.domainPos.get(dom);
                        if (!dp) return null;
                        const active =
                          highlightedIds.size === 0 ||
                          (highlightedIds.has(`domain:${dom}`) && highlightedIds.has(sk.id));
                        const x1 = dp.x + 240;
                        const y1 = dp.y;
                        const x2 = sp.x;
                        const y2 = sp.y;
                        const mx = (x1 + x2) / 2;
                        return (
                          <path
                            key={`ds-${dom}-${sk.id}`}
                            d={`M ${x1} ${y1} C ${mx} ${y1}, ${mx} ${y2}, ${x2} ${y2}`}
                            fill="none"
                            stroke={
                              active
                                ? sk.is_covered
                                  ? "rgba(48, 209, 88, 0.58)"
                                  : "rgba(255, 159, 10, 0.68)"
                                : "rgba(255,255,255,0.05)"
                            }
                            strokeWidth={active ? 1.8 : 0.9}
                          />
                        );
                      });
                    })}

                    {/* Column 1 Nodes: Companies + Role Titles */}
                    {svgLayout.jobsSlice.map((j) => {
                      const pos = svgLayout.jobPos.get(j.id);
                      if (!pos) return null;
                      const isSel = selectedNode?.kind === "job" && selectedNode.job.id === j.id;
                      const dimmed = highlightedIds.size > 0 && !highlightedIds.has(j.id);
                      const label = `${j.company}: ${j.title}`;
                      const shortLabel = label.length > 38 ? `${label.slice(0, 36)}…` : label;
                      return (
                        <g
                          key={j.id}
                          style={{ cursor: "pointer", opacity: dimmed ? 0.28 : 1 }}
                          onClick={() => setSelectedNode({ kind: "job", job: j })}
                        >
                          <rect
                            x={pos.x}
                            y={pos.y - 14}
                            width={280}
                            height={28}
                            rx={8}
                            fill={isSel ? "rgba(10, 132, 255, 0.28)" : "#131c31"}
                            stroke={isSel ? "#0a84ff" : "rgba(255,255,255,0.14)"}
                            strokeWidth={isSel ? 2 : 1}
                          />
                          <text x={pos.x + 10} y={pos.y + 4} fill="#f3f6fc" fontSize={11.5}>
                            {shortLabel}
                          </text>
                        </g>
                      );
                    })}

                    {/* Column 2 Nodes: Domain Clusters */}
                    {svgLayout.domainList.map((dom) => {
                      const pos = svgLayout.domainPos.get(dom);
                      if (!pos) return null;
                      const domObj = graph.domains.find((d) => d.domain === dom);
                      const isSel =
                        selectedNode?.kind === "domain" && selectedNode.domain.domain === dom;
                      const dimmed =
                        highlightedIds.size > 0 && !highlightedIds.has(`domain:${dom}`);
                      const shortDom = dom.length > 30 ? `${dom.slice(0, 28)}…` : dom;
                      return (
                        <g
                          key={dom}
                          style={{ cursor: "pointer", opacity: dimmed ? 0.3 : 1 }}
                          onClick={() => domObj && setSelectedNode({ kind: "domain", domain: domObj })}
                        >
                          <rect
                            x={pos.x}
                            y={pos.y - 16}
                            width={240}
                            height={32}
                            rx={10}
                            fill={isSel ? "rgba(94, 92, 230, 0.36)" : "rgba(10, 132, 255, 0.16)"}
                            stroke={isSel ? "#7d7aff" : "rgba(10, 132, 255, 0.45)"}
                            strokeWidth={isSel ? 2 : 1.2}
                          />
                          <text
                            x={pos.x + 12}
                            y={pos.y + 4}
                            fill="#dbeafe"
                            fontSize={12}
                            fontWeight={600}
                          >
                            {shortDom} ({domObj?.job_count ?? 0})
                          </text>
                        </g>
                      );
                    })}

                    {/* Column 3 Nodes: Extracted Skills */}
                    {svgLayout.skillsSlice.map((sk) => {
                      const pos = svgLayout.skillPos.get(sk.id);
                      if (!pos) return null;
                      const isSel = selectedNode?.kind === "skill" && selectedNode.skill.id === sk.id;
                      const dimmed = highlightedIds.size > 0 && !highlightedIds.has(sk.id);
                      const strokeColor = sk.is_covered
                        ? "rgba(48, 209, 88, 0.65)"
                        : "rgba(255, 159, 10, 0.72)";
                      const fillColor = isSel
                        ? "rgba(255,255,255,0.16)"
                        : sk.is_covered
                        ? "rgba(48, 209, 88, 0.12)"
                        : "rgba(255, 159, 10, 0.14)";
                      const formattedKw = formatSkillName(sk.keyword);
                      const shortKw =
                        formattedKw.length > 26 ? `${formattedKw.slice(0, 24)}…` : formattedKw;
                      return (
                        <g
                          key={sk.id}
                          style={{ cursor: "pointer", opacity: dimmed ? 0.25 : 1 }}
                          onClick={() => setSelectedNode({ kind: "skill", skill: sk })}
                        >
                          <rect
                            x={pos.x}
                            y={pos.y - 13}
                            width={240}
                            height={26}
                            rx={13}
                            fill={fillColor}
                            stroke={isSel ? "#ffffff" : strokeColor}
                            strokeWidth={isSel ? 2 : 1.1}
                          />
                          <text x={pos.x + 12} y={pos.y + 4} fill="#f8fafc" fontSize={11.5}>
                            {shortKw} ({sk.demand_count})
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </div>
              </div>
            )}

            {/* Domain Collections Summary Cards */}
            {graph.domains.length > 0 && (
              <div className="domain-collections-grid">
                {graph.domains.map((dom) => (
                  <div key={dom.domain} className="card-elevated stack-sm">
                    <div className="row-between">
                      <strong style={{ fontSize: 13.5 }}>{dom.domain}</strong>
                      <span className="pill pill-blue">{dom.job_count} jobs</span>
                    </div>
                    <div className="small-note">
                      <strong>Companies:</strong> {dom.companies.slice(0, 6).join(", ")}
                      {dom.companies.length > 6 ? ` +${dom.companies.length - 6}` : ""}
                    </div>
                    <div className="row-wrap">
                      {dom.top_skills.slice(0, 8).map((sk) => (
                        <span
                          key={sk}
                          className={`pill ${
                            dom.missing_skills.includes(sk) ? "pill-amber" : "pill-green"
                          }`}
                        >
                          {formatSkillName(sk)}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
