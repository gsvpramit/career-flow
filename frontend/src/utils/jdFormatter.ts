/** Utilities to format raw scraped job descriptions & extract full skill inventory for reading. */

import type { RoleTrackConfig, WeightedSkill } from "../types";

export type JdBlock =
  | { type: "heading"; text: string }
  | { type: "bullets"; items: string[] }
  | { type: "paragraph"; text: string };

const HTML_ENTITIES: Record<string, string> = {
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'",
  "&nbsp;": " ",
  "&rsquo;": "'",
  "&lsquo;": "'",
  "&rdquo;": '"',
  "&ldquo;": '"',
  "&ndash;": "–",
  "&mdash;": "—",
  "&bull;": "•",
};

const KNOWN_SECTION_HEADING =
  /^(about\s+(us|the\s+role|the\s+team|this\s+role|company)|the\s+role|role\s+overview|what\s+you(?:'ll|\s+will)\s+do|what\s+you\s+bring|responsibilities|key\s+responsibilities|requirements|minimum\s+qualifications|basic\s+qualifications|required\s+qualifications|preferred\s+qualifications|nice\s+to\s+have|bonus\s+points|skills\s+(&|and)\s+experience|who\s+you\s+are|what\s+we\s+offer|compensation(\s+(&|and)\s+benefits)?|benefits(\s+(&|and)\s+perks)?|perks|interview\s+process|equal\s+opportunity)/i;

const EXTRA_TECH_SKILLS = [
  "Python",
  "TypeScript",
  "JavaScript",
  "Go",
  "Golang",
  "Rust",
  "Java",
  "C++",
  "Scala",
  "SQL",
  "NoSQL",
  "PostgreSQL",
  "MySQL",
  "Redis",
  "MongoDB",
  "DynamoDB",
  "Cassandra",
  "Elasticsearch",
  "React",
  "Next.js",
  "Node.js",
  "FastAPI",
  "Django",
  "Flask",
  "Spring Boot",
  "GraphQL",
  "gRPC",
  "REST",
  "WebSockets",
  "Kafka",
  "RabbitMQ",
  "Spark",
  "Airflow",
  "Snowflake",
  "dbt",
  "AWS",
  "GCP",
  "Azure",
  "Docker",
  "Kubernetes",
  "Terraform",
  "Linux",
  "CI/CD",
  "GitHub Actions",
  "Prometheus",
  "Grafana",
  "Datadog",
  "OpenTelemetry",
  "PyTorch",
  "TensorFlow",
  "LangChain",
  "RAG",
  "MCP",
];

export function decodeHtmlText(raw: string): string {
  return raw
    .replace(/&(amp|lt|gt|quot|#39|apos|nbsp|rsquo|lsquo|rdquo|ldquo|ndash|mdash|bull);/gi, (m) => {
      return HTML_ENTITIES[m.toLowerCase()] ?? m;
    })
    .replace(/\r\n/g, "\n")
    .replace(/\u00a0/g, " ");
}

function isLikelyHeading(line: string): boolean {
  const clean = line.trim();
  if (!clean || clean.length > 78) return false;
  if (/^[•\-*\d]/.test(clean)) return false;
  if (KNOWN_SECTION_HEADING.test(clean.replace(/:$/, ""))) return true;
  if (clean.endsWith(":") && clean.split(/\s+/).length <= 8) return true;
  const words = clean.split(/\s+/);
  if (
    words.length <= 5 &&
    !clean.endsWith(".") &&
    !clean.includes(",") &&
    /^[A-Z]/.test(clean) &&
    words.every((w) => /^[A-Z0-9&/()'-]+/.test(w) || /^(of|and|the|to|for|in|at|with)$/i.test(w))
  ) {
    return true;
  }
  return false;
}

/** Convert raw JD text into structured headings, bullet lists, and paragraphs for clean reading. */
export function parseJdIntoBlocks(rawText: string): JdBlock[] {
  const normalized = decodeHtmlText(rawText);
  const lines = normalized.split("\n");
  const blocks: JdBlock[] = [];
  let bulletBuf: string[] = [];
  let paraBuf: string[] = [];

  const flushBullets = () => {
    if (bulletBuf.length > 0) {
      blocks.push({ type: "bullets", items: bulletBuf });
      bulletBuf = [];
    }
  };

  const flushPara = () => {
    if (paraBuf.length > 0) {
      blocks.push({ type: "paragraph", text: paraBuf.join(" ") });
      paraBuf = [];
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      flushBullets();
      flushPara();
      continue;
    }

    const bulletMatch = line.match(/^(?:[•\-\*▪◦‣]+|(?:\d{1,2}[.)]))\s+(.+)$/);
    if (bulletMatch) {
      flushPara();
      bulletBuf.push(bulletMatch[1].trim());
      continue;
    }

    if (isLikelyHeading(line)) {
      flushBullets();
      flushPara();
      blocks.push({ type: "heading", text: line.replace(/:$/, "") });
      continue;
    }

    flushBullets();
    paraBuf.push(line);
  }

  flushBullets();
  flushPara();
  return blocks;
}

export interface AllPostingSkillItem {
  keyword: string;
  priorityLabel: string;
  tier: string;
  jdMentions: number;
  inRequired: boolean;
  fromActiveTrack: boolean;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function countKeywordMentions(rawLower: string, keyword: string): number {
  const escaped = escapeRegex(keyword.toLowerCase().trim());
  if (!escaped) return 0;
  try {
    const re = new RegExp(`(?<![a-z0-9])${escaped}(?![a-z0-9])`, "gi");
    return rawLower.match(re)?.length ?? 0;
  } catch {
    return 0;
  }
}

/**
 * Combine weighted skills from the job's role track with any additional
 * technical skills detected across all tracks or common engineering stacks.
 */
export function extractAllPostingSkills(
  rawText: string,
  weightedSkills: WeightedSkill[],
  roleTracks: RoleTrackConfig[]
): AllPostingSkillItem[] {
  const map = new Map<string, AllPostingSkillItem>();

  for (const ws of weightedSkills) {
    const norm = ws.keyword.trim().toLowerCase();
    if (!norm) continue;
    map.set(norm, {
      keyword: ws.keyword,
      priorityLabel: ws.priority_label,
      tier: ws.tier,
      jdMentions: ws.jd_mentions,
      inRequired: ws.in_required_section,
      fromActiveTrack: true,
    });
  }

  const rawLower = decodeHtmlText(rawText).toLowerCase();
  const candidates: string[] = [];
  for (const track of roleTracks) {
    for (const kwList of Object.values(track.keywords || {})) {
      candidates.push(...kwList);
    }
  }
  candidates.push(...EXTRA_TECH_SKILLS);

  for (const kw of candidates) {
    const clean = kw.trim();
    const norm = clean.toLowerCase();
    if (!norm || map.has(norm)) continue;
    const mentions = countKeywordMentions(rawLower, clean);
    if (mentions > 0) {
      map.set(norm, {
        keyword: clean,
        priorityLabel: "Detected Stack",
        tier: "detected",
        jdMentions: mentions,
        inRequired: false,
        fromActiveTrack: false,
      });
    }
  }

  const tierRank: Record<string, number> = {
    core_must_have: 4,
    important_systems: 3,
    senior_leadership: 2,
    bonus_nice_to_have: 1,
    detected: 0,
  };

  return Array.from(map.values()).sort((a, b) => {
    const rDiff = (tierRank[b.tier] ?? 0) - (tierRank[a.tier] ?? 0);
    if (rDiff !== 0) return rDiff;
    if (b.jdMentions !== a.jdMentions) return b.jdMentions - a.jdMentions;
    return a.keyword.localeCompare(b.keyword);
  });
}
