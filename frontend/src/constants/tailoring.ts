import type { BootstrapEmployerInput } from "../types";
import type { DropdownOptionGroup } from "../components/MultiSelectCheckboxDropdown";

export const DEFAULT_AVOIDED_AI_WORDS: string[] = [
  "slashed",
  "spearheaded",
  "leveraged",
  "utilized",
  "synergized",
  "revolutionized",
  "cutting-edge",
  "state-of-the-art",
  "best-in-class",
  "game-changing",
  "seamlessly",
  "delved",
  "tapestry",
  "holistic",
  "paradigm shift",
  "fostering",
  "orchestrated",
  "pioneered",
  "supercharged",
  "skyrocketed",
  "myriad",
];

export const PAGE_BUDGET_OPTIONS: { value: number; label: string }[] = [
  { value: 1, label: "1 Page (Tight Senior)" },
  { value: 1.5, label: "1.5 Pages (Balanced)" },
  { value: 2, label: "2 Pages (Detailed 5+ YOE)" },
  { value: 3, label: "3 Pages (Executive / Deep Tech)" },
  { value: 4, label: "4 Pages (Comprehensive CV)" },
];

export const BULLET_COUNT_OPTIONS: { value: number | ""; label: string }[] = [
  { value: "", label: "Keep Original Count" },
  { value: 3, label: "3 bullets / role" },
  { value: 4, label: "4 bullets / role" },
  { value: 5, label: "5 bullets / role (Standard)" },
  { value: 6, label: "6 bullets / role" },
  { value: 7, label: "7 bullets / role" },
  { value: 8, label: "8 bullets / role" },
  { value: 10, label: "10 bullets / role (Deep)" },
];

export function buildAvoidedWordsGroups(currentWords: string[]): DropdownOptionGroup[] {
  const combined = Array.from(new Set([...DEFAULT_AVOIDED_AI_WORDS, ...currentWords]));
  return [
    {
      title: "AI Clichés & Words to Exclude (uncheck to allow)",
      items: combined.map((w) => ({
        value: w,
        label: w === "slashed" ? `${w} (Strongly avoid)` : w,
      })),
    },
  ];
}

const SOURCE_DISPLAY_LABELS: Record<string, string> = {
  linkedin: "LinkedIn",
  greenhouse: "Greenhouse",
  ashby: "Ashby",
  lever: "Lever",
  manual: "Manual Paste",
};

const WORK_TYPE_LABELS: Record<string, string> = {
  remote: "Remote",
  hybrid: "Hybrid",
  onsite: "On-Site",
  unspecified: "Mode Unspecified",
};

const JOB_TYPE_LABELS: Record<string, string> = {
  "full-time": "Full-Time",
  contract: "Contract",
  part_time: "Part-Time",
  internship: "Internship",
  unspecified: "Unspecified",
};

export const APPLICATION_STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  resume_created: "Resume Created",
  applied: "Applied",
  screening: "Screening",
  interviewing: "Interviewing",
  offer: "Offer Received",
  rejected: "Rejected",
  skipped: "Skipped",
};

const TECH_SKILL_NAME_MAP: Record<string, string> = {
  aws: "AWS",
  gcp: "GCP",
  "ci/cd": "CI/CD",
  cicd: "CI/CD",
  api: "API",
  apis: "APIs",
  rest: "REST API",
  "rest api": "REST API",
  "restful api": "RESTful API",
  grpc: "gRPC",
  sql: "SQL",
  nosql: "NoSQL",
  rag: "RAG",
  llm: "LLM",
  llms: "LLMs",
  nlp: "NLP",
  ml: "ML",
  ai: "AI",
  "generative ai": "Generative AI",
  sre: "SRE",
  devops: "DevOps",
  cdk: "AWS CDK",
  emr: "AWS EMR",
  s3: "Amazon S3",
  iam: "IAM",
  etl: "ETL",
  sdlc: "SDLC",
  pytorch: "PyTorch",
  tensorflow: "TensorFlow",
  bigquery: "BigQuery",
  postgresql: "PostgreSQL",
  postgres: "PostgreSQL",
  mysql: "MySQL",
  mongodb: "MongoDB",
  redis: "Redis",
  dynamodb: "DynamoDB",
  kafka: "Kafka",
  pyspark: "PySpark",
  spark: "Apache Spark",
  "apache spark": "Apache Spark",
  airflow: "Apache Airflow",
  "apache airflow": "Apache Airflow",
  flink: "Apache Flink",
  "apache flink": "Apache Flink",
  kubernetes: "Kubernetes",
  docker: "Docker",
  redshift: "Amazon Redshift",
  databricks: "Databricks",
  javascript: "JavaScript",
  typescript: "TypeScript",
  nodejs: "Node.js",
  "node.js": "Node.js",
  react: "React",
  nextjs: "Next.js",
  "next.js": "Next.js",
  vue: "Vue.js",
  graphql: "GraphQL",
  fastapi: "FastAPI",
  opentelemetry: "OpenTelemetry",
  prometheus: "Prometheus",
  grafana: "Grafana",
  snowflake: "Snowflake",
  terraform: "Terraform",
  rust: "Rust",
  golang: "Go",
  go: "Go",
  python: "Python",
  java: "Java",
  "c++": "C++",
  observability: "Observability",
  "on-call": "On-Call",
  oncall: "On-Call",
  ownership: "Ownership",
  experimentation: "Experimentation",
  "model evaluation": "Model Evaluation",
  collaboration: "Collaboration",
  "cross-functional": "Cross-Functional",
  "cross-functional collaboration": "Cross-Functional Collaboration",
  reliability: "Reliability",
  "deep learning": "Deep Learning",
  "technical leadership": "Technical Leadership",
  "system design": "System Design",
  "distributed systems": "Distributed Systems",
  "data quality": "Data Quality",
  "event-driven architecture": "Event-Driven Architecture",
  agile: "Agile",
  mentorship: "Mentorship",
  "unit testing": "Unit Testing",
  "integration testing": "Integration Testing",
  "access control": "Access Control",
  "code review": "Code Review",
  latency: "Latency & High Throughput",
  throughput: "Throughput",
  architecture: "Architecture",
};

export function formatSkillName(raw?: string | null): string {
  if (!raw) return "";
  const clean = raw.trim();
  const low = clean.toLowerCase();
  if (TECH_SKILL_NAME_MAP[low]) return TECH_SKILL_NAME_MAP[low];
  return clean
    .split(/(\s+|-|\/)/)
    .map((part) => {
      if (/^(\s+|-|\/)$/.test(part)) return part;
      const partLow = part.toLowerCase();
      if (TECH_SKILL_NAME_MAP[partLow]) return TECH_SKILL_NAME_MAP[partLow];
      if (partLow.length <= 3 && ["aws", "gcp", "sql", "api", "rag", "llm", "nlp", "ml", "ai", "sre"].includes(partLow)) {
        return partLow.toUpperCase();
      }
      return part.charAt(0).toUpperCase() + part.slice(1).toLowerCase();
    })
    .join("");
}

export function formatSourceLabel(source?: string | null): string {
  if (!source) return "Direct";
  const key = source.trim().toLowerCase();
  if (SOURCE_DISPLAY_LABELS[key]) return SOURCE_DISPLAY_LABELS[key];
  return source
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatWorkTypeLabel(workType?: string | null): string {
  if (!workType) return "Mode Unspecified";
  const key = workType.trim().toLowerCase();
  return WORK_TYPE_LABELS[key] || workType.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatJobTypeLabel(jobType?: string | null): string {
  if (!jobType) return "Full-Time";
  const key = jobType.trim().toLowerCase();
  return JOB_TYPE_LABELS[key] || jobType.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatStatusLabel(status?: string | null): string {
  if (!status) return "Ready";
  const key = status.trim().toLowerCase();
  return APPLICATION_STATUS_LABELS[key] || status.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function createDefaultEmployers(): BootstrapEmployerInput[] {
  return [
    {
      company: "Amazon",
      title: "Senior Software Engineer",
      location: "Seattle, WA",
      start_date: "Jan 2023",
      end_date: "Present",
      bullets_count: 6,
    },
    {
      company: "Intuit",
      title: "Software Engineer II",
      location: "San Diego, CA",
      start_date: "Mar 2021",
      end_date: "Dec 2022",
      bullets_count: 5,
    },
  ];
}


