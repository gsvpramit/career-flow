import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { ConfigPanel } from "./components/ConfigPanel";
import { JobPanel } from "./components/JobPanel";
import { ReportsPanel } from "./components/ReportsPanel";
import { ResumePanel } from "./components/ResumePanel";
import { SkillsGraphPanel } from "./components/SkillsGraphPanel";
import { ActivityLogsPanel } from "./components/ActivityLogsPanel";
import { AuthLandingModal, type AuthUser } from "./components/AuthLandingModal";
import { getActivityLogs, subscribeActivityLogs } from "./utils/activityLogger";
import type {
  ConfigResponse,
  ResumeListResponse,
  RoleTrackConfig,
  ScrapeSessionSummary,
  TabId,
} from "./types";

const TABS: { id: TabId; label: string }[] = [
  { id: "sessions", label: "Sessions" },
  { id: "reports", label: "Reports" },
  { id: "skills_graph", label: "Skills Graph" },
  { id: "resume", label: "Resume" },
  { id: "config", label: "Config" },
  { id: "logs", label: "Activity & Logs" },
];

export type ViewportMode = "standard" | "wide" | "maximized";

export default function App() {
  const [activeTab, setActiveTab] = useState<TabId>("sessions");
  const [viewportMode, setViewportMode] = useState<ViewportMode>(() => {
    try {
      const saved = window.localStorage.getItem("careerflow.viewportMode");
      if (saved === "standard" || saved === "wide" || saved === "maximized") return saved;
    } catch {
      // ignore storage errors
    }
    return "maximized";
  });
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [roleTracks, setRoleTracks] = useState<RoleTrackConfig[]>([]);
  const [resumeState, setResumeState] = useState<ResumeListResponse | null>(null);
  const [sessions, setSessions] = useState<ScrapeSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionIdState] = useState<number | null>(() => {
    try {
      const saved = localStorage.getItem("careerflow.activeSessionId");
      return saved ? parseInt(saved, 10) : null;
    } catch {
      return null;
    }
  });
  const setActiveSessionId = useCallback((id: number | null | ((prev: number | null) => number | null)) => {
    setActiveSessionIdState((prev) => {
      const next = typeof id === "function" ? id(prev) : id;
      try {
        if (next != null) {
          localStorage.setItem("careerflow.activeSessionId", String(next));
        } else {
          localStorage.removeItem("careerflow.activeSessionId");
        }
      } catch {
        /* ignore localStorage quota/disabled errors */
      }
      return next;
    });
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [unreadErrorCount, setUnreadErrorCount] = useState<number>(() => {
    return getActivityLogs().filter((l) => !l.read && l.level === "error").length;
  });
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => {
    try {
      const saved = localStorage.getItem("careerflow.auth_user");
      return saved ? JSON.parse(saved) : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    const unsub = subscribeActivityLogs((logs) => {
      setUnreadErrorCount(logs.filter((l) => !l.read && l.level === "error").length);
    });
    return unsub;
  }, []);

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
    let savedId: number | null = null;
    try {
      const saved = localStorage.getItem("careerflow.activeSessionId");
      savedId = saved ? parseInt(saved, 10) : null;
    } catch {
      savedId = null;
    }
    setActiveSessionId((prev) => {
      if (selectId != null && list.some((s) => s.id === selectId)) return selectId;
      if (prev != null && list.some((s) => s.id === prev)) return prev;
      if (savedId != null && list.some((s) => s.id === savedId)) return savedId;
      return list[0]?.id ?? null;
    });
  }, [setActiveSessionId]);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([loadConfigAndTracks(), loadResumes(), loadSessions()]);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to initialize workspace.");
      }
    })();
  }, [loadConfigAndTracks, loadResumes, loadSessions]);

  useEffect(() => {
    try {
      window.localStorage.setItem("careerflow.viewportMode", viewportMode);
    } catch {
      // ignore
    }
  }, [viewportMode]);

  return (
    <div className={`app-shell app-shell-${viewportMode}`}>
      {!currentUser && (
        <AuthLandingModal
          onLoginSuccess={(user) => setCurrentUser(user)}
          currentUser={currentUser}
        />
      )}

      <header className="topbar">
        <div className="brand">
          <h1 className="brand-title">CareerFlow</h1>
          <div className="brand-subtitle">
            Job scraping, skill gaps &amp; tailored resumes
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <nav className="tab-nav" aria-label="Workspace Tabs">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                className={`tab-btn ${activeTab === tab.id ? "active" : ""}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
                {tab.id === "logs" && unreadErrorCount > 0 && (
                  <span
                    className="pill pill-red"
                    style={{ marginLeft: 6, fontSize: 10, padding: "1px 6px", borderRadius: 10 }}
                  >
                    {unreadErrorCount}
                  </span>
                )}
              </button>
            ))}
          </nav>

          {currentUser && (
            <div className="row-wrap" style={{ alignItems: "center", gap: 8, marginLeft: 4 }}>
              <div className="user-badge-chip">
                <span style={{ fontSize: 13 }}>
                  {currentUser.provider === "guest"
                    ? "⚡"
                    : currentUser.provider === "google"
                    ? "🌐"
                    : currentUser.provider === "microsoft"
                    ? "💼"
                    : "👤"}
                </span>
                <span style={{ fontWeight: 600 }}>{currentUser.username}</span>
                {currentUser.notifyEnabled && (
                  <span
                    className="pill pill-green"
                    style={{ fontSize: 10, padding: "1px 6px" }}
                    title={`Job notifications active for ${currentUser.email}`}
                  >
                    Alerts On
                  </span>
                )}
              </div>
              <button
                type="button"
                className="btn btn-sm btn-ghost"
                onClick={() => {
                  try {
                    localStorage.removeItem("careerflow.auth_user");
                  } catch {
                    // ignore
                  }
                  setCurrentUser(null);
                }}
                title="Sign out of CareerFlow"
                style={{ fontSize: 12, padding: "4px 8px" }}
              >
                Sign Out
              </button>
            </div>
          )}
        </div>
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
          onResumesChanged={loadResumes}
          onNavigateTab={setActiveTab}
          viewportMode={viewportMode}
          onChangeViewportMode={setViewportMode}
        />
      )}

      {activeTab === "reports" && (
        <ReportsPanel
          sessions={sessions}
          activeSessionId={activeSessionId}
          onJobsUpdated={loadSessions}
        />
      )}

      {activeTab === "skills_graph" && (
        <SkillsGraphPanel
          sessions={sessions}
          selectedSessionId={activeSessionId}
          roleTracks={roleTracks}
          onRoleTrackUpdated={loadConfigAndTracks}
        />
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
          onDataFlushed={async () => {
            await Promise.all([loadSessions(), loadResumes()]);
          }}
        />
      )}

      {activeTab === "logs" && <ActivityLogsPanel />}
    </div>
  );
}
