"""Cross-track JD skill enrichment, active resume skill inventory, and seniority-based auto-sizing."""

from __future__ import annotations

import re
from typing import Sequence

from backend.app.schemas.job import JobAnalysis, WeightedSkill
from backend.app.schemas.resume import CanonicalResume

# Curated technical skills across backend, full-stack, data, cloud, DevOps, and AI/ML roles.
UNIVERSAL_TECH_TAXONOMY: tuple[tuple[str, str], ...] = (
    ("Python", "important_systems"),
    ("TypeScript", "important_systems"),
    ("JavaScript", "important_systems"),
    ("Java", "important_systems"),
    ("Go", "important_systems"),
    ("Rust", "important_systems"),
    ("C++", "important_systems"),
    ("SQL", "important_systems"),
    ("FastAPI", "important_systems"),
    ("Django", "important_systems"),
    ("Flask", "important_systems"),
    ("Node.js", "important_systems"),
    ("React", "important_systems"),
    ("Next.js", "important_systems"),
    ("GraphQL", "important_systems"),
    ("gRPC", "important_systems"),
    ("RESTful API", "important_systems"),
    ("PostgreSQL", "important_systems"),
    ("MySQL", "important_systems"),
    ("Redis", "important_systems"),
    ("MongoDB", "important_systems"),
    ("DynamoDB", "important_systems"),
    ("Snowflake", "important_systems"),
    ("BigQuery", "important_systems"),
    ("Databricks", "important_systems"),
    ("Apache Spark", "important_systems"),
    ("PySpark", "important_systems"),
    ("Kafka", "important_systems"),
    ("Airflow", "important_systems"),
    ("dbt", "important_systems"),
    ("AWS", "important_systems"),
    ("GCP", "important_systems"),
    ("Azure", "important_systems"),
    ("Docker", "important_systems"),
    ("Kubernetes", "important_systems"),
    ("Terraform", "important_systems"),
    ("CI/CD", "important_systems"),
    ("GitHub Actions", "bonus_nice_to_have"),
    ("Linux", "bonus_nice_to_have"),
    ("Microservices", "important_systems"),
    ("Distributed Systems", "important_systems"),
    ("System Design", "senior_leadership"),
    ("Event-Driven Architecture", "important_systems"),
    ("Observability", "bonus_nice_to_have"),
    ("OpenTelemetry", "bonus_nice_to_have"),
    ("Prometheus", "bonus_nice_to_have"),
    ("Grafana", "bonus_nice_to_have"),
    ("PyTorch", "important_systems"),
    ("TensorFlow", "important_systems"),
    ("LLM", "important_systems"),
    ("Generative AI", "important_systems"),
    ("RAG", "important_systems"),
    ("LangChain", "important_systems"),
    ("LangGraph", "bonus_nice_to_have"),
    ("Vector Database", "bonus_nice_to_have"),
    ("Embeddings", "bonus_nice_to_have"),
    ("Prompt Engineering", "bonus_nice_to_have"),
    ("Fine-Tuning", "bonus_nice_to_have"),
    ("Model Evaluation", "important_systems"),
    ("OAuth2", "bonus_nice_to_have"),
    ("Access Control", "bonus_nice_to_have"),
    ("Caching", "bonus_nice_to_have"),
    ("Unit Testing", "bonus_nice_to_have"),
    ("Integration Testing", "bonus_nice_to_have"),
    ("Mentorship", "senior_leadership"),
    ("Cross-functional Collaboration", "senior_leadership"),
    ("Technical Leadership", "senior_leadership"),
    ("Agile", "bonus_nice_to_have"),
)

_TAXONOMY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "RESTful API": ("rest api", "rest apis", "restful api", "restful apis", "restful services"),
    "Apache Spark": ("apache spark", "spark"),
    "Event-Driven Architecture": ("event-driven", "event driven"),
    "Generative AI": ("generative ai", "genai"),
    "Model Evaluation": (
        "evals",
        "model evaluation",
        "llm evaluation",
        "evaluation benchmarks",
        "evaluation loops",
        "evaluation design",
        "eval-driven",
    ),
    "Observability": ("observability", "telemetry", "audit trails", "auditability", "monitoring"),
    "Access Control": ("access control", "access controls", "rbac", "iam"),
    "CI/CD": ("ci/cd", "cicd", "continuous integration", "continuous deployment"),
    "Vector Database": ("vector database", "vector db", "pinecone", "pgvector", "qdrant", "weaviate"),
    "Go": ("golang", "go"),
}

_TIER_META: dict[str, tuple[str, float]] = {
    "core_must_have": ("Must-Have", 3.0),
    "important_systems": ("Important Systems", 2.0),
    "senior_leadership": ("Seniority / Leadership", 2.0),
    "bonus_nice_to_have": ("Bonus", 1.0),
}


def _compile_kw_regex(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip())
    if re.match(r"^[A-Za-z0-9]", term) and re.search(r"[A-Za-z0-9]$", term):
        return re.compile(rf"(?<![A-Za-z0-9]){escaped}(?![A-Za-z0-9])", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


def enrich_job_weighted_skills(raw_text: str, existing_skills: Sequence[WeightedSkill]) -> list[WeightedSkill]:
    """Supplement single-track skills with genuine cross-track technologies found in the JD text."""
    text = raw_text or ""
    if not text.strip():
        return list(existing_skills)

    by_key: dict[str, WeightedSkill] = {s.keyword.strip().lower(): s for s in existing_skills}
    req_section_hint = ""
    lowered = text.lower()
    for marker in ("requirements", "qualifications", "what you bring", "skills", "must have"):
        idx = lowered.find(marker)
        if idx >= 0:
            req_section_hint += text[idx : idx + 1800] + "\n"

    enriched = list(existing_skills)
    for canonical, default_tier in UNIVERSAL_TECH_TAXONOMY:
        low_key = canonical.lower()
        if low_key in by_key:
            continue
        aliases = _TAXONOMY_SYNONYMS.get(canonical, (canonical,))
        hits = 0
        in_req = False
        for alias in aliases:
            pat = _compile_kw_regex(alias)
            matches = pat.findall(text)
            if matches:
                hits += len(matches)
                if req_section_hint and pat.search(req_section_hint):
                    in_req = True
        if hits <= 0:
            continue
        tier = "core_must_have" if (in_req or hits >= 2) and default_tier == "important_systems" else default_tier
        label, weight = _TIER_META[tier]
        item = WeightedSkill(
            keyword=canonical,
            tier=tier,  # type: ignore[arg-type]
            priority_label=label,
            weight=weight,
            jd_mentions=hits,
            in_required_section=in_req,
        )
        enriched.append(item)
        by_key[low_key] = item

    enriched.sort(key=lambda s: (-s.weight, -s.jd_mentions, s.keyword.lower()))
    return enriched


def extract_all_resume_skills(resume: CanonicalResume, raw_resume_text: str = "") -> list[str]:
    """Return every skill listed on the candidate's Skills section plus recognized technical terms in text."""
    seen_lower: set[str] = set()
    ordered: list[str] = []

    for cat in resume.skills:
        for item in cat.items:
            clean = item.strip()
            if clean and clean.lower() not in seen_lower:
                seen_lower.add(clean.lower())
                ordered.append(clean)

    haystack = raw_resume_text or ""
    if not haystack.strip():
        parts: list[str] = [resume.summary or ""]
        for exp in resume.experience:
            parts.extend(b.text for b in exp.bullets)
        for proj in resume.projects:
            parts.extend(proj.tech_stack)
            parts.extend(b.text for b in proj.bullets)
        haystack = "\n".join(parts)

    for canonical, _ in UNIVERSAL_TECH_TAXONOMY:
        if canonical.lower() in seen_lower:
            continue
        aliases = _TAXONOMY_SYNONYMS.get(canonical, (canonical,))
        if any(_compile_kw_regex(alias).search(haystack) for alias in aliases):
            seen_lower.add(canonical.lower())
            ordered.append(canonical)

    return ordered


_NON_WORK_JD_RE = re.compile(
    r"(?:this role is based in|hybrid work model|days in (?:the )?office|days per week|"
    r"relocation assistance|travel up to \d+%|equal opportunity|affirmative action|"
    r"background checks|reasonable accommodations|applicant privacy|"
    r"\bcompensation range\b|\bbase salary\b|\bbenefits include\b|"
    r"\bhas raised\b|\braised over\b|world-?class investors|\bgrown rapidly\b|"
    r"year[- ]over[- ]year|increasing revenue|\bseries [a-f]\b|\bbacked by\b|\bvaluation\b|^we[’']ve\b)",
    re.IGNORECASE,
)

_ENGINEERING_WORK_HINT_RE = re.compile(
    r"\b(?:design|build|ship|develop|engineer|deploy|architect|scale|lead|own|evaluate|"
    r"model|system|api|pipeline|platform|data|cloud|infra|workflow|service|software|product)\b",
    re.IGNORECASE,
)


def is_non_work_jd_line(text: str) -> bool:
    """Return True when a JD line describes office logistics, fundraising/PR copy, legal notices, or benefits."""
    cleaned = text.strip().lower()
    return cleaned.startswith(("equal opportunity", "benefits", "about ", "we’ve ", "we've ")) or bool(
        _NON_WORK_JD_RE.search(cleaned)
    )


def pick_engineering_work_focus(expected_work: Sequence[str]) -> str:
    """Return the first genuine engineering responsibility clause, skipping logistics and investor blurbs."""
    for item in expected_work:
        cleaned = item.strip().rstrip(".")
        if len(cleaned) < 20 or is_non_work_jd_line(cleaned):
            continue
        first_sentence = re.split(r"\.\s+", cleaned, maxsplit=1)[0].strip()
        if 20 <= len(first_sentence) <= 135 and _ENGINEERING_WORK_HINT_RE.search(first_sentence):
            return first_sentence
    return "Scalable production software and reliable engineering delivery"


def filter_engineering_expected_work(expected_work: Sequence[str]) -> list[str]:
    """Filter out logistics, EEO, and PR/fundraising blurbs from stored JD expectations."""
    return [item for item in expected_work if not is_non_work_jd_line(item)]


def build_missing_requirements(
    *,
    job: JobAnalysis,
    missing_skills: Sequence[WeightedSkill],
    resume_text: str,
) -> list[str]:
    """Build an elaborate list of unmet JD skill requirements, systems expectations, and signals."""
    requirements: list[str] = []
    seen_lower: set[str] = set()

    for ws in sorted(missing_skills, key=lambda x: (-x.weight, -x.jd_mentions, x.keyword.lower())):
        scope = "Required qualification" if ws.in_required_section else ws.priority_label
        entry = f"{ws.keyword} ({scope} · mentioned {ws.jd_mentions}x in JD)"
        if entry.lower() not in seen_lower:
            seen_lower.add(entry.lower())
            requirements.append(entry)

    haystack = resume_text or ""
    for sig in job.detected_signals or []:
        clean_sig = sig.strip()
        if not clean_sig:
            continue
        if not _compile_kw_regex(clean_sig).search(haystack):
            entry = f"Expected signal: {clean_sig}"
            if entry.lower() not in seen_lower:
                seen_lower.add(entry.lower())
                requirements.append(entry)

    for work_item in (job.expected_work or [])[:5]:
        cleaned = work_item.strip().rstrip(".")
        if len(cleaned) < 18 or is_non_work_jd_line(cleaned):
            continue
        keywords_in_line = [
            canonical
            for canonical, _ in UNIVERSAL_TECH_TAXONOMY
            if _compile_kw_regex(canonical).search(cleaned)
        ]
        if any(not _compile_kw_regex(kw).search(haystack) for kw in keywords_in_line) or len(requirements) < 6:
            entry = f"Posting responsibility: {cleaned[:140]}"
            if entry.lower() not in seen_lower:
                seen_lower.add(entry.lower())
                requirements.append(entry)

    return requirements


_SIGNAL_SOFTEN_MAP: dict[str, str] = {
    "ownership": "end-to-end accountability",
    "reliability": "resilience",
    "architecture": "platform design",
    "production": "enterprise",
    "scalability": "elastic capacity",
    "distributed": "multi-node",
    "system design": "systems engineering",
    "latency": "response time",
    "throughput": "request volume",
    "cross-functional": "multi-team",
    "mentorship": "technical coaching",
    "slo": "service target",
    "sla": "uptime commitment",
}


def soften_signal_on_resume(
    draft: CanonicalResume,
    base_resume: CanonicalResume,
    signal: str,
    *,
    include_base_bullets: bool = False,
) -> CanonicalResume | None:
    """Replace an over-stuffed seniority signal token with natural engineering phrasing to keep ATS <= 85%."""
    pat = _compile_kw_regex(signal)
    repl = _SIGNAL_SOFTEN_MAP.get(signal.lower(), "engineering")
    trial = draft.model_copy(deep=True)
    changed = False

    def _replace_signal(text: str) -> tuple[str, bool]:
        if not pat.search(text):
            return text, False
        updated = re.sub(r"\bin production\b", "in live environments", text, flags=re.IGNORECASE) if signal.lower() == "production" else text
        updated = pat.sub(repl, updated)
        updated = re.sub(r"\s{2,}", " ", updated).strip()
        return updated, updated != text

    if trial.summary and pat.search(trial.summary):
        # First clean any "Known for a, b, c across..." summary suffix cleanly
        known_pat = re.compile(r"\s*Known for ([^.]+)\.", re.IGNORECASE)
        m = known_pat.search(trial.summary)
        if m and pat.search(m.group(1)):
            items = [part.strip() for part in m.group(1).split(" across ")[0].split(",") if part.strip()]
            kept = [it for it in items if not pat.search(it)]
            tail = " across " + m.group(1).split(" across ", 1)[1] if " across " in m.group(1) else ""
            if kept:
                replacement = f" Known for {', '.join(kept)}{tail}."
            else:
                replacement = ""
            trial.summary = (trial.summary[: m.start()] + replacement + trial.summary[m.end() :]).strip()
            changed = True
        if pat.search(trial.summary):
            new_sum, did = _replace_signal(trial.summary)
            if did:
                trial.summary = new_sum
                changed = True

    for proj in trial.projects:
        if pat.search(proj.name):
            new_name, did = _replace_signal(proj.name)
            if did:
                proj.name = new_name
                changed = True
        for b in proj.bullets:
            new_b, did = _replace_signal(b.text)
            if did:
                b.text = new_b
                changed = True

    for exp_idx, exp in enumerate(trial.experience):
        base_bullets = base_resume.experience[exp_idx].bullets if exp_idx < len(base_resume.experience) else []
        for b_idx, b in enumerate(exp.bullets):
            if not pat.search(b.text):
                continue
            is_base = b.provenance == "VERIFIED_BASE"
            if is_base and not include_base_bullets:
                continue
            if not is_base and b_idx < len(base_bullets) and not pat.search(base_bullets[b_idx].text):
                b.text = base_bullets[b_idx].text
                b.provenance = base_bullets[b_idx].provenance
                changed = True
                continue
            new_b, did = _replace_signal(b.text)
            if did:
                b.text = new_b
                changed = True

    return trial if changed else None


_DANGLING_PREP_RE = re.compile(
    r"\b(?:with|using|via|for|across|and)\s+(?=(?:supporting|tailored|aligned|validating|to\b|across\b|and\b|[,.]))",
    re.IGNORECASE,
)


def strip_keyword_from_stacks_and_clean_prose(
    trial: CanonicalResume,
    base_resume: CanonicalResume,
    kw: str,
) -> CanonicalResume | None:
    """Remove an over-stuffed keyword from non-base project stacks and clean dangling prepositions."""
    pat = _compile_kw_regex(kw)
    base_proj_stacks = {
        proj.name.lower(): {t.strip().lower() for t in proj.tech_stack}
        for proj in base_resume.projects
    }
    base_text = "\n".join(
        [
            base_resume.summary or "",
            *(b.text for e in base_resume.experience for b in e.bullets),
            *(t for p in base_resume.projects for t in p.tech_stack),
            *(b.text for p in base_resume.projects for b in p.bullets),
        ]
    )
    kw_in_base = bool(pat.search(base_text))

    updated = trial.model_copy(deep=True)
    changed = False

    def _clean_dangling(text: str) -> tuple[str, bool]:
        cleaned = pat.sub("", text) if not kw_in_base else text
        cleaned = _DANGLING_PREP_RE.sub("", cleaned)
        cleaned = re.sub(r"\s+([,.])", r"\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        return cleaned, cleaned != text

    if updated.summary:
        new_sum, did = _clean_dangling(updated.summary)
        if did:
            updated.summary = new_sum
            changed = True

    for proj in updated.projects:
        orig_stack = base_proj_stacks.get(proj.name.lower(), set())
        if not kw_in_base or kw.strip().lower() not in orig_stack:
            filtered_stack = [t for t in proj.tech_stack if not pat.search(t)]
            if len(filtered_stack) != len(proj.tech_stack):
                proj.tech_stack = filtered_stack or proj.tech_stack[:1]
                changed = True
        for b in proj.bullets:
            new_b, did = _clean_dangling(b.text)
            if did:
                b.text = new_b
                changed = True

    for exp in updated.experience:
        for b in exp.bullets:
            if b.provenance == "VERIFIED_BASE":
                continue
            new_b, did = _clean_dangling(b.text)
            if did:
                b.text = new_b
                changed = True

    return updated if changed else None


def compute_smart_seniority_sizing(
    job: JobAnalysis,
    resume: CanonicalResume,
) -> tuple[float, list[int], str]:
    """Choose optimal page budget (1.0 / 1.5 / 2.0) and variable bullet counts per employer.

    For senior / 6-8+ YoE postings, chooses a 2.0 page resume with >= 6 bullets on primary
    roles and natural progression across older roles (e.g. [6, 6, 5] or [6, 5]).
    """
    exp_count = max(1, len(resume.experience))
    title_low = (job.title or "").lower()
    min_yoe = job.yoe.min_years or 0
    max_yoe = job.yoe.max_years or min_yoe

    is_staff_or_senior = (
        max_yoe >= 6
        or min_yoe >= 5
        or any(tok in title_low for tok in ("senior", "sr", "staff", "principal", "lead", "architect", "manager", "fde"))
    )
    is_entry = (
        (0 < max_yoe <= 2)
        or any(tok in title_low for tok in ("junior", "entry", "new grad", "associate", "intern"))
    )

    if is_staff_or_senior and not is_entry:
        page_budget = 2.0
        base_pattern = [6, 6, 5, 4, 4]
        rationale = f"Senior/Lead role profile ({max(min_yoe, max_yoe, 6)}+ YoE): 2.0 pages with {base_pattern[:exp_count]} bullets per role"
    elif is_entry:
        page_budget = 1.0
        base_pattern = [4, 3, 3, 2, 2]
        rationale = f"Entry/Early-Career profile: 1.0 page with {base_pattern[:exp_count]} bullets per role"
    else:
        page_budget = 1.5
        base_pattern = [5, 4, 4, 3, 3]
        rationale = f"Mid-level profile (3-5 YoE): 1.5 pages with {base_pattern[:exp_count]} bullets per role"

    counts = [base_pattern[i] if i < len(base_pattern) else max(3, base_pattern[-1]) for i in range(exp_count)]
    return page_budget, counts, rationale
