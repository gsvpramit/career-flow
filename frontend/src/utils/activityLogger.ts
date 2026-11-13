import type { ActivityLogEntry } from "../types";

const ACTIVITY_LOGS_STORAGE_KEY = "careerflow.activity_logs.v1";
const MAX_LOGS = 200;

type ActivityListener = (logs: ActivityLogEntry[]) => void;
const listeners: Set<ActivityListener> = new Set();

export function getActivityLogs(): ActivityLogEntry[] {
  try {
    const raw = localStorage.getItem(ACTIVITY_LOGS_STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as ActivityLogEntry[];
  } catch {
    return [];
  }
}

export function subscribeActivityLogs(listener: ActivityListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function logActivity(entry: {
  level: "error" | "warning" | "info" | "success";
  source: string;
  title: string;
  message: string;
  details?: string;
}): void {
  try {
    const current = getActivityLogs();
    const newEntry: ActivityLogEntry = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      timestamp: new Date().toISOString(),
      level: entry.level,
      source: entry.source,
      title: entry.title,
      message: entry.message,
      details: entry.details,
      read: false,
    };
    const updated = [newEntry, ...current].slice(0, MAX_LOGS);
    localStorage.setItem(ACTIVITY_LOGS_STORAGE_KEY, JSON.stringify(updated));
    listeners.forEach((fn) => fn(updated));
  } catch {
    // ignore local storage errors
  }
}

export function clearActivityLogs(): void {
  try {
    localStorage.removeItem(ACTIVITY_LOGS_STORAGE_KEY);
    listeners.forEach((fn) => fn([]));
  } catch {
    // ignore
  }
}

export function markAllLogsRead(): void {
  try {
    const current = getActivityLogs();
    const updated = current.map((log) => ({ ...log, read: true }));
    localStorage.setItem(ACTIVITY_LOGS_STORAGE_KEY, JSON.stringify(updated));
    listeners.forEach((fn) => fn(updated));
  } catch {
    // ignore
  }
}
