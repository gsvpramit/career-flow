"""Domain inference and interactive Role x Domain x Skills knowledge graph builder."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import JobPostingRecord, ResumeRecord, ScrapeSessionRecord
from backend.app.schemas.job import (
    JobAnalysis,
    SkillsGraphDomainSummary,
    SkillsGraphEdge,
    SkillsGraphJobNode,
    SkillsGraphResponse,
    SkillsGraphSkillNode,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.config_manager import ConfigManager
from backend.app.services.jd_analyzer import _keyword_pattern
from backend.app.services.label_formatter import format_role_track_label, format_skill_name
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.skill_enrichment import enrich_job_weighted_skills

_DOMAIN_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "AI / LLM & Applied Agents",
        (
            "ai_engineer",
            "ml_engineer",
            "applied_scientist",
            "mlops_ai_infra",
            "llm",
            "rag",
            "generative ai",
            "genai",
            "agent",
            "machine learning",
            "applied scientist",
            "pytorch",
            "inference",
        ),
    ),
    (
        "Data Platforms & Analytics",
        (
            "data_engineer",
            "data_scientist",
            "spark",
            "pyspark",
            "databricks",
            "snowflake",
            "airflow",
            "dbt",
            "etl",
            "data pipeline",
            "analytics",
            "warehouse",
        ),
    ),
    (
        "Cloud & Platform Infrastructure",
        (
            "platform_infra",
            "sre",
            "site reliability",
            "infrastructure",
            "kubernetes",
            "terraform",
            "devops",
            "cloud platform",
            "ci/cd",
        ),
    ),
    (
        "Security & Privacy Engineering",
        (
            "security_engineer",
            "appsec",
            "security",
            "cryptography",
            "zero trust",
            "oauth",
            "iam",
            "vulnerability",
        ),
    ),
    (
        "Forward Deployed & Customer Systems",
        (
            "fde",
            "solutions_architect",
            "forward deployed",
            "solutions architect",
            "solutions engineer",
            "customer engineering",
            "field engineer",
        ),
    ),
    (
        "Full-Stack & Product Engineering",
        (
            "fullstack_product",
            "founding_engineer",
            "full-stack",
            "full stack",
            "frontend",
            "react",
            "next.js",
            "product engineer",
        ),
    ),
]

_DOMAIN_FOUNDATIONAL_SKILLS: dict[str, list[tuple[str, str, str]]] = {
    # (Skill Name, Tier, Priority Label)
    "Full-Stack & Product Engineering": [
        ("TypeScript", "core_must_have", "Must-Have"),
        ("React", "core_must_have", "Must-Have"),
        ("Node.js", "core_must_have", "Must-Have"),
        ("Next.js", "important_systems", "Important"),
        ("REST API", "core_must_have", "Must-Have"),
        ("GraphQL", "important_systems", "Important"),
        ("PostgreSQL", "important_systems", "Important"),
        ("Docker", "important_systems", "Important"),
        ("CI/CD", "bonus_nice_to_have", "Bonus"),
        ("System Design", "senior_leadership", "Seniority / Architecture"),
    ],
    "Distributed Systems & Backend": [
        ("Distributed Systems", "core_must_have", "Must-Have"),
        ("Microservices", "core_must_have", "Must-Have"),
        ("Kafka", "important_systems", "Important"),
        ("gRPC", "important_systems", "Important"),
        ("Redis", "important_systems", "Important"),
        ("Kubernetes", "important_systems", "Important"),
        ("Observability", "bonus_nice_to_have", "Bonus"),
        ("Latency & High Throughput", "senior_leadership", "Seniority / Architecture"),
    ],
    "AI / LLM & Applied Agents": [
        ("Python", "core_must_have", "Must-Have"),
        ("PyTorch", "core_must_have", "Must-Have"),
        ("LLMs", "core_must_have", "Must-Have"),
        ("RAG", "core_must_have", "Must-Have"),
        ("Vector Databases", "important_systems", "Important"),
        ("Model Evaluation", "important_systems", "Important"),
        ("Agents & Tool Calling", "important_systems", "Important"),
    ],
    "Data Platforms & Analytics": [
        ("Python", "core_must_have", "Must-Have"),
        ("SQL", "core_must_have", "Must-Have"),
        ("PySpark", "core_must_have", "Must-Have"),
        ("Apache Airflow", "core_must_have", "Must-Have"),
        ("Kafka", "important_systems", "Important"),
        ("BigQuery", "important_systems", "Important"),
        ("Data Modeling", "important_systems", "Important"),
        ("ETL", "core_must_have", "Must-Have"),
    ],
    "Cloud & Platform Infrastructure": [
        ("Kubernetes", "core_must_have", "Must-Have"),
        ("Docker", "core_must_have", "Must-Have"),
        ("Terraform", "core_must_have", "Must-Have"),
        ("AWS", "core_must_have", "Must-Have"),
        ("CI/CD", "core_must_have", "Must-Have"),
        ("Linux", "important_systems", "Important"),
        ("Observability", "important_systems", "Important"),
    ],
}


def classify_job_domain(role_track: str, title: str, raw_text: str = "") -> str:
    """Classify a posting into a clean engineering domain bucket for reporting and skills-graph views."""
    track = (role_track or "").strip().lower()
    title_l = (title or "").strip().lower()
    snippet = (raw_text or "")[:1200].lower()

    # Exact track anchors first
    for domain_label, keywords in _DOMAIN_RULES:
        if track in keywords:
            return domain_label

    scores: list[tuple[int, str]] = []
    for domain_label, keywords in _DOMAIN_RULES:
        pts = 0
        for kw in keywords:
            if kw in title_l:
                pts += 3
            elif kw in snippet:
                pts += 1
        if pts > 0:
            scores.append((pts, domain_label))

    if scores:
        scores.sort(key=lambda item: (-item[0], item[1]))
        return scores[0][1]

    return "Distributed Systems & Backend"


def build_skills_graph(
    db: Session,
    config_manager: ConfigManager,
    session_id: int | None = None,
) -> SkillsGraphResponse:
    """Build a structured Company x Role x Domain <-> Skills network graph from active postings."""
    sess_name = "All Sessions"
    if session_id is not None:
        sess_row = db.get(ScrapeSessionRecord, session_id)
        if sess_row is not None:
            sess_name = sess_row.name

    job_stmt = select(JobPostingRecord).where(JobPostingRecord.disposition != "discarded")
    if session_id is not None:
        job_stmt = job_stmt.where(JobPostingRecord.session_id == session_id)
    jobs = list(db.scalars(job_stmt.order_by(JobPostingRecord.relevance_score.desc(), JobPostingRecord.id.desc())).all())

    resumes = list(db.scalars(select(ResumeRecord)).all())
    resume_texts: list[tuple[str, str]] = []
    for res in resumes:
        parsed = CanonicalResume.model_validate_json(res.content_json)
        plain = f"{res.raw_text}\n{resume_to_plain_text(parsed)}"
        resume_texts.append((res.name, plain))

    total_jobs = len(jobs)
    if total_jobs == 0:
        return SkillsGraphResponse(
            session_id=session_id,
            session_name=sess_name,
            total_jobs=0,
        )

    skill_meta: dict[str, dict[str, object]] = {}
    job_nodes: list[SkillsGraphJobNode] = []
    edges: list[SkillsGraphEdge] = []
    seen_domain_skill_edges: set[tuple[str, str]] = set()

    domain_jobs: dict[str, list[JobPostingRecord]] = defaultdict(list)
    domain_companies: dict[str, set[str]] = defaultdict(set)
    domain_tracks: dict[str, set[str]] = defaultdict(set)
    domain_skill_counts: dict[str, Counter[str]] = defaultdict(Counter)

    for j in jobs:
        analysis = JobAnalysis.model_validate_json(j.analysis_json)
        weighted = enrich_job_weighted_skills(j.raw_text, analysis.weighted_skills)
        domain = classify_job_domain(j.role_track, j.title, j.raw_text)
        role_label = format_role_track_label(j.role_track or "senior_swe", config_manager)
        company = (j.company or "Unknown").strip()
        job_node_id = f"job:{j.id}"
        domain_node_id = f"domain:{domain}"

        domain_jobs[domain].append(j)
        if company:
            domain_companies[domain].add(company)
        domain_tracks[domain].add(role_label)

        edges.append(
            SkillsGraphEdge(
                source=job_node_id,
                target=domain_node_id,
                kind="job_domain",
                weight=1.0,
                tier="important_systems",
            )
        )

        top_job_skills: list[str] = []
        seen_in_job: set[str] = set()
        for ws in sorted(weighted, key=lambda x: (-float(x.weight), -int(x.jd_mentions), x.keyword)):
            low = ws.keyword.strip().lower()
            if not low or low in seen_in_job:
                continue
            seen_in_job.add(low)
            top_job_skills.append(ws.keyword)
            domain_skill_counts[domain][low] += 1

            entry = skill_meta.get(low)
            if entry is None:
                entry = {
                    "keyword": ws.keyword,
                    "tier": ws.tier,
                    "priority_label": ws.priority_label,
                    "job_ids": set(),
                    "domains": set(),
                    "companies": set(),
                    "role_tracks": set(),
                }
                skill_meta[low] = entry
            elif ws.tier == "core_must_have":
                entry["tier"] = ws.tier
                entry["priority_label"] = ws.priority_label

            entry["job_ids"].add(j.id)  # type: ignore[union-attr]
            entry["domains"].add(domain)  # type: ignore[union-attr]
            if company:
                entry["companies"].add(company)  # type: ignore[union-attr]
            entry["role_tracks"].add(role_label)  # type: ignore[union-attr]

            skill_node_id = f"skill:{low}"
            edges.append(
                SkillsGraphEdge(
                    source=job_node_id,
                    target=skill_node_id,
                    kind="job_skill",
                    weight=float(ws.weight),
                    tier=ws.tier,
                )
            )
            if (domain_node_id, skill_node_id) not in seen_domain_skill_edges:
                seen_domain_skill_edges.add((domain_node_id, skill_node_id))
                edges.append(
                    SkillsGraphEdge(
                        source=domain_node_id,
                        target=skill_node_id,
                        kind="domain_skill",
                        weight=float(ws.weight),
                        tier=ws.tier,
                    )
                )

        job_nodes.append(
            SkillsGraphJobNode(
                id=job_node_id,
                job_id=j.id,
                title=j.title,
                company=company,
                location=(j.location or "").strip() or "Unspecified",
                role_track=j.role_track or "senior_swe",
                role_label=role_label,
                domain=domain,
                relevance_score=float(j.relevance_score or 0.0),
                skill_count=len(top_job_skills),
                skills=top_job_skills[:14],
            )
        )

    # Bind foundational industry skills to active domains so candidates see the real-world complete stack
    for dom in domain_jobs:
        foundational = _DOMAIN_FOUNDATIONAL_SKILLS.get(dom, [])
        domain_node_id = f"domain:{dom}"
        for f_kw, f_tier, f_prio in foundational:
            low = f_kw.strip().lower()
            if low not in skill_meta:
                skill_meta[low] = {
                    "keyword": f_kw,
                    "tier": f_tier,
                    "priority_label": f_prio,
                    "job_ids": set(),
                    "domains": {dom},
                    "companies": set(),
                    "role_tracks": set(domain_tracks.get(dom, set())),
                }
            else:
                skill_meta[low]["domains"].add(dom)  # type: ignore[union-attr]

            domain_skill_counts[dom][low] = max(domain_skill_counts[dom][low], 1)

            skill_node_id = f"skill:{low}"
            if (domain_node_id, skill_node_id) not in seen_domain_skill_edges:
                seen_domain_skill_edges.add((domain_node_id, skill_node_id))
                edges.append(
                    SkillsGraphEdge(
                        source=domain_node_id,
                        target=skill_node_id,
                        kind="domain_skill",
                        weight=3.0 if f_tier == "core_must_have" else 2.0,
                        tier=f_tier,
                    )
                )

    skill_nodes: list[SkillsGraphSkillNode] = []
    covered_count = 0
    missing_count = 0
    covered_by_low: dict[str, bool] = {}

    for low, meta in skill_meta.items():
        kw = str(meta["keyword"])
        display_kw = format_skill_name(kw)
        pat = _keyword_pattern(kw)
        covered_by = [r_name for r_name, r_text in resume_texts if pat.search(r_text)]
        is_cov = len(covered_by) > 0
        covered_by_low[low] = is_cov
        if is_cov:
            covered_count += 1
        else:
            missing_count += 1

        j_ids = sorted(meta["job_ids"])  # type: ignore[arg-type]
        effective_demand_count = max(len(j_ids), 1 if meta["domains"] else 0)
        skill_nodes.append(
            SkillsGraphSkillNode(
                id=f"skill:{low}",
                keyword=display_kw,
                tier=str(meta["tier"]),
                priority_label=str(meta["priority_label"]),
                demand_count=effective_demand_count,
                demand_pct=round((effective_demand_count / max(1, total_jobs)) * 100.0, 1),
                covered_by_resumes=covered_by,
                is_covered=is_cov,
                domains=sorted(meta["domains"]),  # type: ignore[arg-type]
                companies=sorted(meta["companies"]),  # type: ignore[arg-type]
                role_tracks=sorted(meta["role_tracks"]),  # type: ignore[arg-type]
                job_ids=j_ids,
            )
        )

    skill_nodes.sort(key=lambda s: (-s.demand_count, s.is_covered, s.keyword.lower()))

    domain_summaries: list[SkillsGraphDomainSummary] = []
    for dom, dom_job_rows in sorted(domain_jobs.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        top_lows = [k for k, _ in domain_skill_counts[dom].most_common(12)]
        top_labels = [format_skill_name(str(skill_meta[k]["keyword"])) for k in top_lows if k in skill_meta]
        missing_labels = [
            format_skill_name(str(skill_meta[k]["keyword"]))
            for k in top_lows
            if k in skill_meta and not covered_by_low.get(k, False)
        ]
        domain_summaries.append(
            SkillsGraphDomainSummary(
                domain=dom,
                job_count=len(dom_job_rows),
                companies=sorted(domain_companies[dom]),
                role_tracks=sorted(domain_tracks[dom]),
                top_skills=top_labels,
                missing_skills=missing_labels,
            )
        )

    return SkillsGraphResponse(
        session_id=session_id,
        session_name=sess_name,
        total_jobs=total_jobs,
        total_skills=len(skill_nodes),
        covered_skills=covered_count,
        missing_skills=missing_count,
        jobs=job_nodes,
        skills=skill_nodes,
        edges=edges,
        domains=domain_summaries,
    )
