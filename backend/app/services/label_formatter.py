"""Human-readable, properly capitalized display labels for tracks, statuses, filters, and sources."""

from __future__ import annotations

from backend.app.services.config_manager import ConfigManager

APPLICATION_STATUS_LABELS: dict[str, str] = {
    "ready": "Ready to Tailor",
    "resume_created": "Resume Created",
    "applied": "Applied",
    "screening": "Screening",
    "interviewing": "Interviewing",
    "offer": "Offer Received",
    "rejected": "Rejected",
    "skipped": "Skipped",
    "discarded": "Discarded",
}

FILTER_REASON_LABELS: dict[str, str] = {
    "stale_outside_window": "Stale / Outside Time Window",
    "role_mismatch": "Target Role Mismatch",
    "duplicate_in_batch": "Duplicate in Batch",
    "already_seen_discarded": "Already Seen (Previously Discarded)",
    "already_seen_saved": "Already Seen (Already Saved)",
    "already_seen_filtered": "Already Seen (Previously Filtered)",
    "already_seen": "Already Seen",
    "seen:saved": "Seen: Saved",
    "seen:auto_filtered": "Seen: Auto-Filtered",
    "seen:filtered": "Seen: Auto-Filtered",
    "seen:discarded": "Seen: Discarded",
    "seen:skipped": "Seen: Skipped",
    "no_h1b_sponsorship": "No H1B / Visa Sponsorship",
    "salary_below_floor": "Compensation Below Floor",
    "location_mismatch": "Location Mismatch",
    "experience_out_of_range": "Years of Experience Out of Range",
    "internship_or_contract": "Internship / Contract Filtered",
}

SOURCE_LABELS: dict[str, str] = {
    "linkedin": "LinkedIn",
    "greenhouse": "Greenhouse ATS",
    "lever": "Lever ATS",
    "ashby": "Ashby ATS",
    "indeed": "Indeed",
    "builtin": "Built In",
    "wellfound": "Wellfound",
    "hn": "Hacker News Who Is Hiring",
    "manual": "Manual Import",
}

UPPER_ACRONYMS: set[str] = {
    "ai", "ml", "swe", "fde", "api", "apis", "sql", "aws", "gcp",
    "ci", "cd", "h1b", "us", "uk", "ats", "llm", "nlp", "sre", "etl"
}

TECH_SKILL_NAME_MAP: dict[str, str] = {
    "aws": "AWS",
    "gcp": "GCP",
    "ci/cd": "CI/CD",
    "cicd": "CI/CD",
    "api": "API",
    "apis": "APIs",
    "rest": "REST API",
    "rest api": "REST API",
    "restful api": "RESTful API",
    "grpc": "gRPC",
    "sql": "SQL",
    "nosql": "NoSQL",
    "rag": "RAG",
    "llm": "LLM",
    "llms": "LLMs",
    "nlp": "NLP",
    "ml": "ML",
    "ai": "AI",
    "generative ai": "Generative AI",
    "sre": "SRE",
    "devops": "DevOps",
    "cdk": "AWS CDK",
    "emr": "AWS EMR",
    "s3": "Amazon S3",
    "iam": "IAM",
    "etl": "ETL",
    "sdlc": "SDLC",
    "pytorch": "PyTorch",
    "tensorflow": "TensorFlow",
    "bigquery": "BigQuery",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "dynamodb": "DynamoDB",
    "kafka": "Kafka",
    "pyspark": "PySpark",
    "spark": "Apache Spark",
    "apache spark": "Apache Spark",
    "airflow": "Apache Airflow",
    "apache airflow": "Apache Airflow",
    "flink": "Apache Flink",
    "apache flink": "Apache Flink",
    "kubernetes": "Kubernetes",
    "docker": "Docker",
    "redshift": "Amazon Redshift",
    "databricks": "Databricks",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "nodejs": "Node.js",
    "node.js": "Node.js",
    "react": "React",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "vue": "Vue.js",
    "graphql": "GraphQL",
    "fastapi": "FastAPI",
    "opentelemetry": "OpenTelemetry",
    "prometheus": "Prometheus",
    "grafana": "Grafana",
    "snowflake": "Snowflake",
    "terraform": "Terraform",
    "rust": "Rust",
    "golang": "Go",
    "go": "Go",
    "python": "Python",
    "java": "Java",
    "c++": "C++",
    "observability": "Observability",
    "on-call": "On-Call",
    "oncall": "On-Call",
    "ownership": "Ownership",
    "experimentation": "Experimentation",
    "model evaluation": "Model Evaluation",
    "collaboration": "Collaboration",
    "cross-functional": "Cross-Functional",
    "cross-functional collaboration": "Cross-Functional Collaboration",
    "reliability": "Reliability",
    "deep learning": "Deep Learning",
    "technical leadership": "Technical Leadership",
    "system design": "System Design",
    "distributed systems": "Distributed Systems",
    "data quality": "Data Quality",
    "event-driven architecture": "Event-Driven Architecture",
    "agile": "Agile",
    "mentorship": "Mentorship",
    "unit testing": "Unit Testing",
    "integration testing": "Integration Testing",
    "access control": "Access Control",
    "code review": "Code Review",
    "latency": "Latency & High Throughput",
    "throughput": "Throughput",
    "architecture": "Architecture",
}


def format_skill_name(raw: str | None) -> str:
    """Format technical skills, tools, and competencies with industry Title/Tech casing."""
    clean = (raw or "").strip()
    if not clean:
        return ""
    low = clean.lower()
    if low in TECH_SKILL_NAME_MAP:
        return TECH_SKILL_NAME_MAP[low]
    words = clean.split()
    formatted_words: list[str] = []
    for w in words:
        if "-" in w:
            parts = [TECH_SKILL_NAME_MAP.get(p.lower(), p[:1].upper() + p[1:].lower()) for p in w.split("-")]
            formatted_words.append("-".join(parts))
        elif "/" in w:
            parts = [TECH_SKILL_NAME_MAP.get(p.lower(), p.upper() if len(p) <= 3 else p[:1].upper() + p[1:].lower()) for p in w.split("/")]
            formatted_words.append("/".join(parts))
        elif w.lower() in UPPER_ACRONYMS:
            formatted_words.append(w.upper())
        elif w.lower() in TECH_SKILL_NAME_MAP:
            formatted_words.append(TECH_SKILL_NAME_MAP[w.lower()])
        else:
            formatted_words.append(w[:1].upper() + w[1:].lower())
    return " ".join(formatted_words)


def humanize_slug(raw: str, fallback: str = "Unspecified") -> str:
    """Convert any snake_case, kebab-case, or colon-prefixed identifier into clean Title Case."""
    clean = (raw or "").strip()
    if not clean:
        return fallback
    if ":" in clean:
        prefix, rest = clean.split(":", 1)
        return f"{humanize_slug(prefix)}: {humanize_slug(rest)}"
    parts = [p for p in clean.replace("-", "_").split("_") if p]
    if not parts:
        return fallback
    out: list[str] = []
    for part in parts:
        low = part.lower()
        if low in UPPER_ACRONYMS:
            out.append(low.upper())
        else:
            out.append(part[:1].upper() + part[1:].lower())
    return " ".join(out)


def format_role_track_label(track_id: str, config_manager: ConfigManager | None = None) -> str:
    """Resolve a role_track ID to its proper display title."""
    clean = (track_id or "").strip()
    if not clean:
        return "Unspecified Role"
    if config_manager is not None:
        try:
            track = config_manager.get_role_track(clean)
            if track and track.display_name:
                return track.display_name
        except Exception:
            pass
    default_tracks = {
        "senior_swe": "Senior Software Engineer",
        "mid_swe": "Software Engineer (Mid-Level)",
        "junior_swe": "Junior / Entry Software Engineer",
        "staff_swe": "Staff / Principal Software Engineer",
        "fde": "Forward Deployed Engineer (FDE)",
        "ai_engineer": "AI / ML Engineer",
        "fullstack_product": "Full Stack Product Engineer",
        "backend_systems": "Backend / Distributed Systems Engineer",
        "data_engineer": "Data Engineer",
        "platform_infra": "Platform / Infrastructure Engineer",
        "security_engineer": "Security Engineer",
    }
    return default_tracks.get(clean.lower(), humanize_slug(clean))


def format_status_label(status_id: str) -> str:
    """Format an application status or disposition slug for Reports and UI pills."""
    clean = (status_id or "").strip().lower()
    return APPLICATION_STATUS_LABELS.get(clean, humanize_slug(clean, "Ready to Tailor"))


def format_filter_reason_label(reason_id: str) -> str:
    """Format an inline filter reason slug cleanly."""
    clean = (reason_id or "").strip()
    if not clean:
        return "Filtered"
    low = clean.lower()
    if low in FILTER_REASON_LABELS:
        return FILTER_REASON_LABELS[low]
    return humanize_slug(clean, "Filtered")


def format_source_label(source_id: str) -> str:
    """Format a scraping source identifier cleanly."""
    clean = (source_id or "").strip().lower()
    base = clean.split(":")[0]
    if base in SOURCE_LABELS:
        return SOURCE_LABELS[base]
    return humanize_slug(base, "Manual Import")
