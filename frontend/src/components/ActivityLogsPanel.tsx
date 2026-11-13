import { useEffect, useMemo, useState } from "react";
import type { ActivityLogEntry } from "../types";
import {
  clearActivityLogs,
  getActivityLogs,
  markAllLogsRead,
  subscribeActivityLogs,
} from "../utils/activityLogger";
import { formatEasternDateTime } from "../utils/datetime";

export function ActivityLogsPanel() {
  const [logs, setLogs] = useState<ActivityLogEntry[]>(() => getActivityLogs());
  const [filterLevel, setFilterLevel] = useState<"all" | "error" | "warning" | "tailoring" | "scraper">("all");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    markAllLogsRead();
    const unsub = subscribeActivityLogs((next) => setLogs(next));
    return unsub;
  }, []);

  const counts = useMemo(() => {
    let errors = 0;
    let warnings = 0;
    let tailoring = 0;
    let scraper = 0;
    for (const log of logs) {
      if (log.level === "error") errors++;
      if (log.level === "warning") warnings++;
      if (log.source.toLowerCase().includes("tailor") || log.source.toLowerCase().includes("llm")) tailoring++;
      if (log.source.toLowerCase().includes("scrap")) scraper++;
    }
    return { all: logs.length, errors, warnings, tailoring, scraper };
  }, [logs]);

  const filteredLogs = useMemo(() => {
    const q = search.trim().toLowerCase();
    return logs.filter((log) => {
      if (filterLevel === "error" && log.level !== "error") return false;
      if (filterLevel === "warning" && log.level !== "warning") return false;
      if (filterLevel === "tailoring" && !log.source.toLowerCase().includes("tailor") && !log.source.toLowerCase().includes("llm")) return false;
      if (filterLevel === "scraper" && !log.source.toLowerCase().includes("scrap")) return false;

      if (q) {
        const text = `${log.title} ${log.message} ${log.source} ${log.details || ""}`.toLowerCase();
        if (!text.includes(q)) return false;
      }
      return true;
    });
  }, [logs, filterLevel, search]);

  const handleExportJSON = () => {
    const blob = new Blob([JSON.stringify(logs, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `careerflow_activity_logs_${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="stack-lg">
      <div className="card stack-md">
        <div className="row-between" style={{ alignItems: "flex-start", flexWrap: "wrap", gap: 12 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20 }}>Activity Logs</h2>
            <div className="small-note">
              Captures structured runtime telemetry, tailoring runs, scrape batches, validation alerts, and model connections gracefully without disruptive popups.
            </div>
          </div>

          <div className="row-wrap" style={{ gap: 8 }}>
            <button
              type="button"
              className="btn btn-sm"
              onClick={handleExportJSON}
              disabled={logs.length === 0}
            >
              Export Logs JSON
            </button>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={() => {
                if (window.confirm("Are you sure you want to clear all activity and diagnostics logs?")) {
                  clearActivityLogs();
                }
              }}
              disabled={logs.length === 0}
            >
              Clear Logs
            </button>
          </div>
        </div>

        {/* Filter bar */}
        <div className="row-between" style={{ flexWrap: "wrap", gap: 10 }}>
          <div className="row-wrap" style={{ gap: 6 }}>
            <button
              type="button"
              className={`btn btn-sm ${filterLevel === "all" ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setFilterLevel("all")}
            >
              All Events ({counts.all})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${filterLevel === "error" ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setFilterLevel("error")}
              style={counts.errors > 0 ? { borderColor: "var(--accent-red)", color: "var(--accent-red)" } : undefined}
            >
              Errors ({counts.errors})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${filterLevel === "warning" ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setFilterLevel("warning")}
            >
              Warnings ({counts.warnings})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${filterLevel === "tailoring" ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setFilterLevel("tailoring")}
            >
              Tailoring &amp; AI ({counts.tailoring})
            </button>
            <button
              type="button"
              className={`btn btn-sm ${filterLevel === "scraper" ? "btn-primary" : "btn-secondary"}`}
              onClick={() => setFilterLevel("scraper")}
            >
              Scrapes ({counts.scraper})
            </button>
          </div>

          <div style={{ minWidth: 260, flex: "0 1 300px" }}>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search event title, source, or message..."
              style={{ padding: "6px 12px", fontSize: 13 }}
            />
          </div>
        </div>

        {/* Logs List */}
        {filteredLogs.length === 0 ? (
          <div className="alert alert-info" style={{ margin: "16px 0" }}>
            {logs.length === 0
              ? "Zero events logged yet. Tailoring runs, scrapes, and system checks will record here automatically."
              : "No activity logs match the selected filter."}
          </div>
        ) : (
          <div className="stack-xs" style={{ margin: "8px 0" }}>
            {filteredLogs.map((log) => {
              const isExpanded = expandedId === log.id;
              const levelPillClass =
                log.level === "error"
                  ? "pill pill-red"
                  : log.level === "warning"
                  ? "pill pill-amber"
                  : log.level === "success"
                  ? "pill pill-green"
                  : "pill pill-blue";

              return (
                <div
                  key={log.id}
                  style={{
                    padding: "10px 14px",
                    borderRadius: 8,
                    background: "rgba(255, 255, 255, 0.025)",
                    border: `1px solid ${log.level === "error" ? "rgba(239, 68, 68, 0.3)" : "var(--border-subtle)"}`,
                    display: "flex",
                    flexDirection: "column",
                    gap: 6,
                  }}
                >
                  <div className="row-between" style={{ alignItems: "center", flexWrap: "wrap", gap: 8 }}>
                    <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                      <span className={levelPillClass} style={{ textTransform: "uppercase", fontSize: 11, fontWeight: 700 }}>
                        {log.level}
                      </span>
                      <span className="pill" style={{ fontSize: 11.5 }}>
                        {log.source}
                      </span>
                      <strong style={{ fontSize: 13.5 }}>{log.title}</strong>
                    </div>

                    <div className="row-wrap" style={{ alignItems: "center", gap: 8 }}>
                      <span className="small-note mono" style={{ fontSize: 12 }}>
                        {formatEasternDateTime(log.timestamp)}
                      </span>
                      {log.details && (
                        <button
                          type="button"
                          className="btn btn-sm"
                          style={{ padding: "2px 8px", fontSize: 11 }}
                          onClick={() => setExpandedId(isExpanded ? null : log.id)}
                        >
                          {isExpanded ? "Hide Details" : "Inspect Details"}
                        </button>
                      )}
                    </div>
                  </div>

                  <div style={{ fontSize: 13, color: "var(--text-secondary)", lineHeight: 1.4 }}>
                    {log.message}
                  </div>

                  {isExpanded && log.details && (
                    <pre
                      style={{
                        margin: "6px 0 0",
                        padding: "8px 12px",
                        borderRadius: 6,
                        background: "rgba(0, 0, 0, 0.4)",
                        border: "1px solid var(--border-subtle)",
                        fontSize: 12,
                        whiteSpace: "pre-wrap",
                        wordBreak: "break-all",
                        maxHeight: 280,
                        overflowY: "auto",
                      }}
                    >
                      {log.details}
                    </pre>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
