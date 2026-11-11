import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ConfigPanel } from "./components/ConfigPanel";
import { JobPanel } from "./components/JobPanel";
import { ReportsPanel } from "./components/ReportsPanel";
import { ResumePanel } from "./components/ResumePanel";
import { SkillsGapPanel } from "./components/SkillsGapPanel";
import type {
  ConfigResponse,
  ResumeListResponse,
  RoleTrackConfig,
  ScrapeSessionSummary,
  TabId,
} from "./types";

const TABS: { id: TabId; label: string }[] = [
  { id: "sessions", label: "Sessions" },
  { id: "skills_gap", label: "Skills Gap" },
  { id: "reports", label: "Reports" },
  { id: "resume", label: "Resume" },
  { id: "config", label: "Config" },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("sessions");
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [roleTracks, setRoleTracks] = useState<RoleTrackConfig[]>([]);
  const [resumeState, setResumeState] = useState<ResumeListResponse | null>(null);
  const [sessions, setSessions] = useState<ScrapeSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadConfigAndTracks = useCallback(async () => {
    const [cfg, tracks] = await Promise.all([api.getConfig(), api.getRoleTracks()]);
    setConfig(cfg);
    setRoleTracks(tracks);
  }, []);

  const loadResumes = useCallback(async () => {
    const state = await api.listResumes();
    setResumeState(state);
  }, []);

  const loadSessions = useCallback(async (selectId?: number) => {
    const list = await api.listSessions();
    setSessions(list);
    setActiveSessionId((prev) => {
      if (selectId != null && list.some((s) => s.id === selectId)) return selectId;
      if (prev != null && list.some((s) => s.id === prev)) return prev;
      return list[0]?.id ?? null;
    });
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([loadConfigAndTracks(), loadResumes(), loadSessions()]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to initialize workspace.");
      }
    })();
  }, [loadConfigAndTracks, loadResumes, loadSessions]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <h1 className="brand-title">CareerFlow</h1>
          <div className="brand-subtitle">
            Job scraping, skill gaps &amp; tailored resumes
          </div>
        </div>

        <nav className="tab-nav" aria-label="Workspace Tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </header>

      {error && (
        <div className="alert alert-error" style={{ marginBottom: 16 }}>
          {error}
        </div>
      )}

      {activeTab === "sessions" && (
        <JobPanel
          config={config}
          sessions={sessions}
          activeSessionId={activeSessionId}
          onSelectSession={setActiveSessionId}
          roleTracks={roleTracks}
          resumeState={resumeState}
          onSessionsChanged={loadSessions}
          onNavigateTab={setActiveTab}
        />
      )}

      {activeTab === "skills_gap" && (
        <SkillsGapPanel
          sessions={sessions}
          activeSessionId={activeSessionId}
          roleTracks={roleTracks}
          onNavigateTab={setActiveTab}
        />
      )}

      {activeTab === "reports" && (
        <ReportsPanel sessions={sessions} activeSessionId={activeSessionId} />
      )}

      {activeTab === "resume" && (
        <ResumePanel
          resumeState={resumeState}
          roleTracks={roleTracks}
          onRefresh={loadResumes}
        />
      )}

      {activeTab === "config" && (
        <ConfigPanel
          config={config}
          roleTracks={roleTracks}
          onUpdated={loadConfigAndTracks}
        />
      )}
    </div>
  );
}
