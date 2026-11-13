/** Shared US Eastern (America/New_York) date/time formatting helpers. */

export const EASTERN_TIME_ZONE = "America/New_York";

/**
 * Parse API ISO timestamps safely. SQLite strips UTC offsets when persisting
 * naive timestamps, so timezone-less strings are normalized to UTC ('Z') first.
 */
export function parseApiTimestamp(iso: string): Date {
  const trimmed = iso.trim();
  if (!trimmed) return new Date(NaN);
  const hasZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const normalized = hasZone
    ? trimmed
    : `${trimmed.includes("T") ? trimmed : trimmed.replace(" ", "T")}Z`;
  return new Date(normalized);
}

/** Format an ISO timestamp consistently in US Eastern Time (EST / EDT). */
export function formatEasternDateTime(iso?: string | null): string {
  if (!iso) return "—";
  const d = parseApiTimestamp(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-US", {
    timeZone: EASTERN_TIME_ZONE,
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

/** Format relative age alongside US Eastern timestamp for job postings. */
export function formatPostedAtEastern(iso?: string | null): string {
  if (!iso) return "Posting timestamp unavailable";
  const d = parseApiTimestamp(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const formatted = formatEasternDateTime(iso);
  const diffMin = Math.round((Date.now() - d.getTime()) / 60000);
  if (diffMin < 0 || diffMin > 60 * 24 * 60) return formatted;
  if (diffMin < 60) return `${formatted} (${diffMin}m ago)`;
  const diffHours = Math.floor(diffMin / 60);
  if (diffHours < 48) return `${formatted} (${diffHours}h ago)`;
  return `${formatted} (${Math.floor(diffHours / 24)}d ago)`;
}
