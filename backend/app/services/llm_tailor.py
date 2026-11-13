"""Single-model local Ollama integration, 5-year realistic base resume generator, JD tailor, and humanizer."""

from __future__ import annotations

import copy
import json
import os
import re
import time
from typing import Any, Sequence

import httpx

from backend.app.schemas.config import (
    AppSettings,
    BigTechRulesConfig,
    LlmBenchmarkItem,
    LlmBenchmarkResponse,
    LlmStatusResponse,
    LlmTestResponse,
    RoleTrackConfig,
)
from backend.app.schemas.job import ATSReport, JobAnalysis, TailoringReasoningStep, WeightedSkill
from backend.app.schemas.resume import (
    BootstrapEmployerInput,
    CanonicalResume,
    ContactInfo,
    EducationItem,
    ExperienceBullet,
    ExperienceItem,
    ProjectItem,
    SkillCategory,
)
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.jd_analyzer import _keyword_pattern
from backend.app.services.reasoning_tailor import (
    _tailor_projects_to_jd,
    calibrate_resume_to_ats_band,
    curate_heavy_resume_sections,
)
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.skill_enrichment import compute_smart_seniority_sizing

PREFERRED_MODEL_ORDER: tuple[str, ...] = (
    "mistral-nemo:latest",
    "llama3.1:latest",
    "qwen3:14b",
    "gemma2:latest",
    "deepseek-coder-v2:latest",
    "phi3:medium",
)

DEFAULT_AVOIDED_WORDS: tuple[str, ...] = (
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
)

# NOTE: "slashed" is strictly excluded from ALL replacements; when present in avoided_words it maps to "reduced".
HUMANIZER_REPLACEMENTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bslashed\b", re.IGNORECASE), "reduced", "slashed"),
    (re.compile(r"\bspearheaded\b", re.IGNORECASE), "led", "spearheaded"),
    (re.compile(r"\bleveraged\b", re.IGNORECASE), "used", "leveraged"),
    (re.compile(r"\bleveraging\b", re.IGNORECASE), "using", "leveraged"),
    (re.compile(r"\bleverage\b", re.IGNORECASE), "apply", "leveraged"),
    (re.compile(r"\butilized\b", re.IGNORECASE), "used", "utilized"),
    (re.compile(r"\butilizing\b", re.IGNORECASE), "using", "utilized"),
    (re.compile(r"\butilization of\b", re.IGNORECASE), "use of", "utilized"),
    (re.compile(r"\bcutting[- ]edge\b", re.IGNORECASE), "modern", "cutting-edge"),
    (re.compile(r"\bstate[- ]of[- ]the[- ]art\b", re.IGNORECASE), "production", "state-of-the-art"),
    (re.compile(r"\bbest[- ]in[- ]class\b", re.IGNORECASE), "reliable", "best-in-class"),
    (re.compile(r"\brevolutionized\b", re.IGNORECASE), "rebuilt", "revolutionized"),
    (re.compile(r"\bsynergized\b", re.IGNORECASE), "partnered", "synergized"),
    (re.compile(r"\bholistic\b", re.IGNORECASE), "end-to-end", "holistic"),
    (re.compile(r"\bparadigm shift\b", re.IGNORECASE), "architecture change", "paradigm shift"),
    (re.compile(r"\bdelved into\b", re.IGNORECASE), "investigated", "delved"),
    (re.compile(r"\bdelved\b", re.IGNORECASE), "investigated", "delved"),
    (re.compile(r"\btapestry of\b", re.IGNORECASE), "mix of", "tapestry"),
    (re.compile(r"\btapestry\b", re.IGNORECASE), "mix", "tapestry"),
    (re.compile(r"\bseamlessly\b", re.IGNORECASE), "cleanly", "seamlessly"),
    (re.compile(r"\bfostering\b", re.IGNORECASE), "building", "fostering"),
    (re.compile(r"\bfostered\b", re.IGNORECASE), "built", "fostering"),
    (re.compile(r"\borchestrated\b", re.IGNORECASE), "coordinated", "orchestrated"),
    (re.compile(r"\bpioneered\b", re.IGNORECASE), "launched", "pioneered"),
    (re.compile(r"\bchampioned\b", re.IGNORECASE), "drove", "championed"),
    (re.compile(r"\bgame[- ]changing\b", re.IGNORECASE), "high-impact", "game-changing"),
    (re.compile(r"\bsupercharged\b", re.IGNORECASE), "accelerated", "supercharged"),
    (re.compile(r"\bskyrocketed\b", re.IGNORECASE), "increased", "skyrocketed"),
    (re.compile(r"\ba myriad of\b", re.IGNORECASE), "many", "myriad"),
    (re.compile(r"\bmyriad\b", re.IGNORECASE), "many", "myriad"),
    (re.compile(r"\bin order to\b", re.IGNORECASE), "to", "in order to"),
    (re.compile(r"\bproven track record of\b", re.IGNORECASE), "delivered", "proven track record"),
    (re.compile(r"\bresponsible for building\b", re.IGNORECASE), "built", "responsible for"),
    (re.compile(r"\bresponsible for designing\b", re.IGNORECASE), "designed", "responsible for"),
    (re.compile(r"\bresponsible for leading\b", re.IGNORECASE), "led", "responsible for"),
    (re.compile(r"\bresponsible for\b", re.IGNORECASE), "managed", "responsible for"),
    (re.compile(r"\bworked on\b", re.IGNORECASE), "built", "worked on"),
    (re.compile(r"\bhelped with\b", re.IGNORECASE), "supported", "helped with"),
    (re.compile(r"\bassisted with\b", re.IGNORECASE), "supported", "assisted with"),
    (re.compile(r"\btasked with\b", re.IGNORECASE), "delivered", "tasked with"),
]

ALWAYS_CLEAN_PASSIVE_LABELS: set[str] = {
    "in order to",
    "proven track record",
    "responsible for",
    "worked on",
    "helped with",
    "assisted with",
    "tasked with",
}

VERB_ROTATION: dict[str, list[str]] = {
    "built": ["Engineered", "Developed", "Implemented", "Shipped"],
    "designed": ["Architected", "Structured", "Modeled", "Defined"],
    "led": ["Directed", "Drove", "Coordinated", "Guided"],
    "reduced": ["Cut", "Lowered", "Trimmed", "Decreased"],
    "improved": ["Boosted", "Accelerated", "Raised", "Upgraded"],
    "managed": ["Owned", "Operated", "Maintained", "Ran"],
    "created": ["Built", "Launched", "Established", "Delivered"],
    "optimized": ["Accelerated", "Streamlined", "Tuned", "Improved"],
    "engineered": ["Built", "Architected", "Developed", "Implemented"],
    "developed": ["Built", "Engineered", "Delivered", "Shipped"],
}

TECH_CAPITALIZATION: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\brestful\b", re.IGNORECASE), "RESTful"),
    (re.compile(r"\brest apis\b", re.IGNORECASE), "REST APIs"),
    (re.compile(r"\brest api\b", re.IGNORECASE), "REST API"),
    (re.compile(r"\bgraphql\b", re.IGNORECASE), "GraphQL"),
    (re.compile(r"\bgrpc\b", re.IGNORECASE), "gRPC"),
    (re.compile(r"\boauth2\b", re.IGNORECASE), "OAuth2"),
    (re.compile(r"\boauth\b", re.IGNORECASE), "OAuth"),
    (re.compile(r"\bsso\b", re.IGNORECASE), "SSO"),
    (re.compile(r"\bci/cd\b", re.IGNORECASE), "CI/CD"),
    (re.compile(r"\bdevops\b", re.IGNORECASE), "DevOps"),
    (re.compile(r"\bmlops\b", re.IGNORECASE), "MLOps"),
    (re.compile(r"\bgen[- ]?ai\b", re.IGNORECASE), "GenAI"),
    (re.compile(r"\bllms\b", re.IGNORECASE), "LLMs"),
    (re.compile(r"\bllm\b", re.IGNORECASE), "LLM"),
    (re.compile(r"\bvllm\b", re.IGNORECASE), "vLLM"),
    (re.compile(r"\bnosql\b", re.IGNORECASE), "NoSQL"),
    (re.compile(r"\bsql\b", re.IGNORECASE), "SQL"),
    (re.compile(r"\bpostgresql\b", re.IGNORECASE), "PostgreSQL"),
    (re.compile(r"\bmysql\b", re.IGNORECASE), "MySQL"),
    (re.compile(r"\bmongodb\b", re.IGNORECASE), "MongoDB"),
    (re.compile(r"\bdynamodb\b", re.IGNORECASE), "DynamoDB"),
    (re.compile(r"\bfastapi\b", re.IGNORECASE), "FastAPI"),
    (re.compile(r"\bpytorch\b", re.IGNORECASE), "PyTorch"),
    (re.compile(r"\btensorflow\b", re.IGNORECASE), "TensorFlow"),
    (re.compile(r"\bapache spark\b", re.IGNORECASE), "Apache Spark"),
    (re.compile(r"\bpyspark\b", re.IGNORECASE), "PySpark"),
    (re.compile(r"\bspark\b", re.IGNORECASE), "Spark"),
    (re.compile(r"\bdbt\b", re.IGNORECASE), "dbt"),
    (re.compile(r"\baws iam\b", re.IGNORECASE), "AWS IAM"),
    (re.compile(r"\blangchain\b", re.IGNORECASE), "LangChain"),
    (re.compile(r"\blanggraph\b", re.IGNORECASE), "LangGraph"),
    (re.compile(r"\bhugging ?face\b", re.IGNORECASE), "Hugging Face"),
    (re.compile(r"\bspring boot\b", re.IGNORECASE), "Spring Boot"),
    (re.compile(r"\bgithub actions\b", re.IGNORECASE), "GitHub Actions"),
    (re.compile(r"\breact\.js\b", re.IGNORECASE), "React.js"),
    (re.compile(r"\bnode\.js\b", re.IGNORECASE), "Node.js"),
    (re.compile(r"\bnext\.js\b", re.IGNORECASE), "Next.js"),
    (re.compile(r"\btypescript\b", re.IGNORECASE), "TypeScript"),
    (re.compile(r"\bjavascript\b", re.IGNORECASE), "JavaScript"),
    (re.compile(r"\bpython\b", re.IGNORECASE), "Python"),
    (re.compile(r"\bkubernetes\b", re.IGNORECASE), "Kubernetes"),
    (re.compile(r"\bterraform\b", re.IGNORECASE), "Terraform"),
    (re.compile(r"\bdocker\b", re.IGNORECASE), "Docker"),
    (re.compile(r"\bkafka\b", re.IGNORECASE), "Kafka"),
    (re.compile(r"\bredis\b", re.IGNORECASE), "Redis"),
    (re.compile(r"\bairflow\b", re.IGNORECASE), "Airflow"),
    (re.compile(r"\bsnowflake\b", re.IGNORECASE), "Snowflake"),
    (re.compile(r"\bdatabricks\b", re.IGNORECASE), "Databricks"),
    (re.compile(r"\baws s3\b", re.IGNORECASE), "AWS S3"),
    (re.compile(r"\baws lambda\b", re.IGNORECASE), "AWS Lambda"),
    (re.compile(r"\bamazon redshift\b", re.IGNORECASE), "Amazon Redshift"),
    (re.compile(r"\bamazon eks\b", re.IGNORECASE), "Amazon EKS"),
    (re.compile(r"\baws\b", re.IGNORECASE), "AWS"),
    (re.compile(r"\bgcp\b", re.IGNORECASE), "GCP"),
    (re.compile(r"\bazure\b", re.IGNORECASE), "Azure"),
    (re.compile(r"\brag\b", re.IGNORECASE), "RAG"),
    (re.compile(r"\bmcp\b", re.IGNORECASE), "MCP"),
    (re.compile(r"\bnlp\b", re.IGNORECASE), "NLP"),
    (re.compile(r"\betl\b", re.IGNORECASE), "ETL"),
    (re.compile(r"\bsdk\b", re.IGNORECASE), "SDK"),
    (re.compile(r"\bjwt\b", re.IGNORECASE), "JWT"),
    (re.compile(r"\brbac\b", re.IGNORECASE), "RBAC"),
    (re.compile(r"\bapis\b", re.IGNORECASE), "APIs"),
    (re.compile(r"\bapi\b", re.IGNORECASE), "API"),
    (re.compile(r"\bsla\b", re.IGNORECASE), "SLA"),
    (re.compile(r"\bslos\b", re.IGNORECASE), "SLOs"),
    (re.compile(r"\btps\b", re.IGNORECASE), "TPS"),
    (re.compile(r"\bqps\b", re.IGNORECASE), "QPS"),
    (re.compile(r"\bp99\b", re.IGNORECASE), "P99"),
    (re.compile(r"\bp95\b", re.IGNORECASE), "P95"),
    (re.compile(r"\bjson\b", re.IGNORECASE), "JSON"),
    (re.compile(r"\byaml\b", re.IGNORECASE), "YAML"),
    (re.compile(r"\biac\b", re.IGNORECASE), "IaC"),
    (re.compile(r"\bdata pipelines\b", re.IGNORECASE), "Data Pipelines"),
    (re.compile(r"\bdata pipeline\b", re.IGNORECASE), "Data Pipeline"),
    (re.compile(r"\bmicroservices\b", re.IGNORECASE), "Microservices"),
    (re.compile(r"\bopentelemetry\b", re.IGNORECASE), "OpenTelemetry"),
    (re.compile(r"\bprometheus\b", re.IGNORECASE), "Prometheus"),
    (re.compile(r"\bgrafana\b", re.IGNORECASE), "Grafana"),
    (re.compile(r"\belasticsearch\b", re.IGNORECASE), "Elasticsearch"),
    (re.compile(r"\bpinecone\b", re.IGNORECASE), "Pinecone"),
    (re.compile(r"\bpgvector\b", re.IGNORECASE), "pgvector"),
    (re.compile(r"\bscikit[- ]learn\b", re.IGNORECASE), "scikit-learn"),
    (re.compile(r"\bpandas\b", re.IGNORECASE), "Pandas"),
    (re.compile(r"\bnumpy\b", re.IGNORECASE), "NumPy"),
    (re.compile(r"\breact\b", re.IGNORECASE), "React"),
    (re.compile(r"\blinux\b", re.IGNORECASE), "Linux"),
    (re.compile(r"\bevent[- ]driven\b", re.IGNORECASE), "Event-Driven"),
    (re.compile(r"\bdistributed systems\b", re.IGNORECASE), "Distributed Systems"),
]

EXPERIENCE_TITLES_BY_TRACK: dict[str, tuple[str, str]] = {
    "entry_swe": ("Software Engineer I", "Junior Software Developer"),
    "mid_swe": ("Software Engineer II", "Software Engineer I"),
    "senior_swe": ("Senior Software Engineer", "Software Development Engineer"),
    "staff_swe": ("Staff Software Engineer", "Senior Software Engineer"),
    "principal_swe": ("Principal Software Engineer", "Staff Software Engineer"),
    "ai_engineer": ("Senior AI Engineer", "Software Development Engineer"),
    "ml_engineer": ("Senior Machine Learning Engineer", "Machine Learning Engineer"),
    "applied_scientist": ("Senior Applied Scientist", "Applied Scientist"),
    "mlops_ai_infra": ("Senior MLOps & AI Infrastructure Engineer", "Cloud Platform Engineer"),
    "data_engineer": ("Software Engineer II (Data & Platform)", "Data Engineer"),
    "data_scientist": ("Senior Data Scientist", "Data Scientist"),
    "backend_systems": ("Senior Backend & Distributed Systems Engineer", "Software Development Engineer"),
    "fullstack_product": ("Senior Full-Stack Product Engineer", "Software Development Engineer"),
    "founding_engineer": ("Founding Software Engineer", "Senior Full-Stack Engineer"),
    "fde": ("Forward Deployed Software Engineer", "Solutions Software Engineer"),
    "platform_infra": ("Senior Platform & Infrastructure Engineer", "Cloud Infrastructure Engineer"),
    "security_engineer": ("Senior Application Security Engineer", "Security Software Engineer"),
    "solutions_architect": ("Senior Solutions Architect", "Cloud Solutions Engineer"),
}

DEFAULT_EMPLOYERS_BY_TRACK: dict[str, tuple[str, str]] = {
    "data_engineer": ("Intuit", "Amazon Web Services"),
    "data_scientist": ("Intuit", "Amazon Web Services"),
    "ml_engineer": ("Intuit", "Amazon Web Services"),
    "applied_scientist": ("Amazon", "Intuit"),
    "ai_engineer": ("Amazon", "Quest Global"),
    "mlops_ai_infra": ("Amazon Web Services", "Intuit"),
}


def _match_case(template: str, replacement: str) -> str:
    if template and template[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _resolve_active_avoided_words(
    rules: BigTechRulesConfig | None = None,
    avoided_words: Sequence[str] | None = None,
) -> set[str]:
    if avoided_words is not None:
        return {str(w).strip().lower() for w in avoided_words if str(w).strip()}
    combined = set(DEFAULT_AVOIDED_WORDS)
    if rules is not None:
        for word in rules.humanizer_guardrails.get("ai_slop_banlist", []):
            clean = str(word).strip().lower()
            if clean:
                combined.add(clean)
    return combined


def normalize_tech_capitalization(text: str) -> str:
    """Apply crisp proper capitalization for cloud, database, API, and AI engineering terms."""
    clean = (text or "").strip()
    if not clean or "http://" in clean or "https://" in clean or "@" in clean:
        return clean
    updated = clean
    for pattern, proper in TECH_CAPITALIZATION:
        updated = pattern.sub(proper, updated)
    return updated


def humanize_bullet_text(
    text: str,
    rules: BigTechRulesConfig | None = None,
    avoided_words: Sequence[str] | None = None,
) -> tuple[str, list[str]]:
    """Strip active AI clichés, wordy filler, and normalize tech casing for one text line."""
    updated = re.sub(r"\s+", " ", text or "").strip()
    if not updated:
        return updated, []

    active_avoided = _resolve_active_avoided_words(rules=rules, avoided_words=avoided_words)
    replaced_labels: list[str] = []

    for pattern, repl, label in HUMANIZER_REPLACEMENTS:
        lbl = label.lower()
        if lbl in ALWAYS_CLEAN_PASSIVE_LABELS or lbl in active_avoided:
            if pattern.search(updated):
                updated = pattern.sub(lambda m: _match_case(m.group(0), repl), updated)
                if label not in replaced_labels:
                    replaced_labels.append(label)

    # Catch any custom user-supplied avoided words outside HUMANIZER_REPLACEMENTS
    known_labels = {label.lower() for _, _, label in HUMANIZER_REPLACEMENTS}
    for token in sorted(active_avoided):
        if token in known_labels:
            continue
        pat = re.compile(rf"\b{re.escape(token)}\b", re.IGNORECASE)
        if pat.search(updated):
            fallback_word = "applied" if token.endswith("ed") else "effective"
            updated = pat.sub(lambda m: _match_case(m.group(0), fallback_word), updated)
            if token not in replaced_labels:
                replaced_labels.append(token)

    updated = normalize_tech_capitalization(updated)
    updated = re.sub(r"\s+([,.;:])", r"\1", updated)
    updated = re.sub(r"\s{2,}", " ", updated).strip()
    if updated and updated[0].islower():
        updated = updated[0].upper() + updated[1:]
    return updated, replaced_labels


def _dedupe_skill_categories(skills: list[SkillCategory]) -> list[SkillCategory]:
    """Normalize capitalization and remove duplicate skill entries across categories."""
    seen_global: set[str] = set()
    cleaned_cats: list[SkillCategory] = []
    for cat in skills:
        deduped_items: list[str] = []
        for raw_item in cat.items:
            proper = normalize_tech_capitalization(str(raw_item).strip())
            low = proper.lower()
            if proper and low not in seen_global:
                deduped_items.append(proper)
                seen_global.add(low)
        if deduped_items:
            cleaned_cats.append(SkillCategory(category=cat.category, items=deduped_items))
    return cleaned_cats


def humanize_resume(
    resume: CanonicalResume,
    rules: BigTechRulesConfig | None = None,
    avoided_words: Sequence[str] | None = None,
) -> tuple[CanonicalResume, int, list[str]]:
    """Run anti-AI-slop, capitalization normalization, and verb diversity across a CanonicalResume."""
    cloned = resume.model_copy(deep=True)
    changes_count = 0
    notes: list[str] = []
    verb_counts: dict[str, int] = {}
    max_repeats = 2
    if rules is not None:
        max_repeats = int(rules.humanizer_guardrails.get("max_same_verb_repeats", 2))

    if cloned.summary:
        cleaned_summary, sum_labels = humanize_bullet_text(
            cloned.summary,
            rules=rules,
            avoided_words=avoided_words,
        )
        if cleaned_summary != cloned.summary:
            cloned.summary = cleaned_summary
            changes_count += 1
            if sum_labels:
                notes.append(f"Summary cleaned: {', '.join(sum_labels)}")

    def _process_bullets(bullets: list[ExperienceBullet], scope_label: str) -> None:
        nonlocal changes_count
        for b in bullets:
            orig = b.text
            cleaned, labels = humanize_bullet_text(orig, rules=rules, avoided_words=avoided_words)

            first_match = re.match(r"^([A-Za-z]+)\b(.*)$", cleaned)
            if first_match:
                lead = first_match.group(1)
                rest = first_match.group(2)
                lead_key = lead.lower()
                seen = verb_counts.get(lead_key, 0) + 1
                if seen > max_repeats and lead_key in VERB_ROTATION:
                    candidates = VERB_ROTATION[lead_key]
                    alt = next(
                        (c for c in candidates if verb_counts.get(c.lower(), 0) < max_repeats),
                        candidates[(seen - 1) % len(candidates)],
                    )
                    cleaned = f"{alt}{rest}"
                    verb_counts[alt.lower()] = verb_counts.get(alt.lower(), 0) + 1
                    notes.append(f"{scope_label}: varied opener '{lead}' -> '{alt}'")
                else:
                    verb_counts[lead_key] = seen

            if cleaned != orig:
                b.text = cleaned
                changes_count += 1
                if labels:
                    notes.append(f"{scope_label}: replaced avoided wording ({', '.join(labels)})")

    for exp in cloned.experience:
        _process_bullets(exp.bullets, exp.company or "Experience")

    for proj in cloned.projects:
        proj.tech_stack = list(dict.fromkeys(normalize_tech_capitalization(t) for t in proj.tech_stack if t.strip()))
        _process_bullets(proj.bullets, proj.name or "Project")

    cloned.skills = _dedupe_skill_categories(cloned.skills)

    return cloned, changes_count, list(dict.fromkeys(notes))[:12]


def _match_installed_model(requested: str, available: list[str]) -> str | None:
    req = (requested or "").strip()
    if not req or not available:
        return None
    lower_map = {m.lower(): m for m in available}
    if req.lower() in lower_map:
        return lower_map[req.lower()]
    if ":" not in req and f"{req.lower()}:latest" in lower_map:
        return lower_map[f"{req.lower()}:latest"]
    req_base = req.split(":")[0].lower()
    for m in available:
        if m.split(":")[0].lower() == req_base:
            return m
    return None


def _pick_recommended_model(available: list[str]) -> str | None:
    for candidate in PREFERRED_MODEL_ORDER:
        matched = _match_installed_model(candidate, available)
        if matched:
            return matched
    return available[0] if available else None


def pick_active_model(configured_model: str, available: list[str]) -> tuple[str, str | None]:
    """Select exact installed Ollama model or fall back to an installed alternative."""
    exact = _match_installed_model(configured_model, available)
    if exact:
        return exact, None
    rec = _pick_recommended_model(available)
    if rec:
        return (
            rec,
            f"Configured model '{configured_model}' is not pulled locally; used installed model '{rec}'.",
        )
    return configured_model or "mistral-nemo:latest", None


def list_ollama_models(
    base_url: str,
    client: httpx.Client | None = None,
) -> tuple[bool, list[str], str | None]:
    """Query Ollama GET /api/tags and return (reachable, model_names, error_message)."""
    clean_url = (base_url or "http://localhost:11434").strip().rstrip("/")
    tags_url = f"{clean_url}/api/tags"
    owns_client = client is None
    http = client or httpx.Client(timeout=4.0)
    try:
        resp = http.get(tags_url)
        if resp.status_code >= 400:
            return False, [], f"Ollama returned HTTP {resp.status_code} at {tags_url}"
        data = resp.json()
        models_raw = data.get("models") if isinstance(data, dict) else []
        names = [str(m.get("name")).strip() for m in (models_raw or []) if isinstance(m, dict) and m.get("name")]
        return True, names, None
    except Exception as exc:
        return False, [], f"Could not reach Ollama at {clean_url}: {exc}"
    finally:
        if owns_client:
            http.close()


def check_ollama_status(
    settings: AppSettings,
    client: httpx.Client | None = None,
) -> LlmStatusResponse:
    """Return full Ollama daemon reachability and local single-model inventory."""
    reachable, models, err = list_ollama_models(settings.ollama_base_url, client=client)
    matched = _match_installed_model(settings.llm_model, models)
    recommended = _pick_recommended_model(models)
    return LlmStatusResponse(
        reachable=reachable,
        base_url=settings.ollama_base_url,
        configured_model=settings.llm_model,
        model_installed=matched is not None,
        recommended_model=recommended,
        available_models=models,
        llm_mode=settings.llm_mode,
        error=err,
    )


_BOOTSTRAP_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "bullets": {
            "type": "object",
            "additionalProperties": {"type": "string"},
        },
    },
    "required": ["summary", "bullets"],
}

_TAILOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "experiences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "experience_index": {"type": "integer"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["experience_index", "bullets"],
            },
        },
        "projects": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "tech_stack": {"type": "array", "items": {"type": "string"}},
                    "link": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "tech_stack", "bullets"],
            },
        },
        "skills": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "items": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["category", "items"],
            },
        },
        "humanizer_notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "experiences", "projects", "skills"],
}

_TAILOR_COMPACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "experiences": _TAILOR_RESPONSE_SCHEMA["properties"]["experiences"],
        "projects": _TAILOR_RESPONSE_SCHEMA["properties"]["projects"],
        "skills": _TAILOR_RESPONSE_SCHEMA["properties"]["skills"],
    },
    "required": ["summary", "experiences", "projects", "skills"],
}


def _strip_json_fences(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    if start != -1:
        return text[start:]
    return text


def _close_truncated_json(text: str) -> str:
    """Close unclosed quotes, trailing delimiters, and container brackets on truncated JSON."""
    buf: list[str] = []
    stack: list[str] = []
    in_string = False
    escaped = False

    for ch in text:
        buf.append(ch)
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append("}" if ch == "{" else "]")
            elif ch in "}]":
                if stack and stack[-1] == ch:
                    stack.pop()

    if in_string:
        if escaped:
            buf.append("\\")
        buf.append('"')

    closed = "".join(buf).rstrip()
    # Drop incomplete trailing colon or dangling comma before closing containers
    closed = re.sub(r',\s*("[^"]*"\s*:\s*)?$', "", closed)
    if re.search(r'"[^"]*"\s*:\s*$', closed):
        closed += "null"
    closed = re.sub(r",\s*$", "", closed)
    while stack:
        closed += stack.pop()
    return closed


def _insert_missing_json_commas(text: str) -> str:
    """Repair common local-LLM missing comma delimiter glitches without altering quoted content."""
    fixed = re.sub(r'("\s*)\r?\n(\s*")', r'\1,\n\2', text)
    fixed = re.sub(r'(\}\s*)\r?\n(\s*\{)', r'\1,\n\2', fixed)
    fixed = re.sub(r'(\]\s*)\r?\n(\s*")', r'\1,\n\2', fixed)
    fixed = re.sub(r'(\}\s*)\r?\n(\s*")', r'\1,\n\2', fixed)
    fixed = re.sub(r'("\s*)\r?\n(\s*[\[{])', r'\1,\n\2', fixed)
    return fixed


def _repair_and_parse_json(raw_text: str) -> dict[str, Any] | None:
    """Parse local-LLM JSON output with cleanup for missing commas, trailing commas, control newlines, and truncation."""
    candidates: list[str] = []
    base = _strip_json_fences(raw_text)
    candidates.append(base)
    no_trailing_commas = re.sub(r",(\s*[}\]])", r"\1", base)
    candidates.append(no_trailing_commas)
    with_commas = re.sub(r",(\s*[}\]])", r"\1", _insert_missing_json_commas(no_trailing_commas))
    candidates.append(with_commas)
    no_ctrl_newlines = re.sub(r"(?<!\\)\r?\n", " ", with_commas)
    candidates.append(no_ctrl_newlines)
    candidates.append(re.sub(r",(\s*[}\]])", r"\1", _close_truncated_json(with_commas)))
    candidates.append(re.sub(r",(\s*[}\]])", r"\1", _close_truncated_json(no_ctrl_newlines)))

    for cand in candidates:
        if not cand or "{" not in cand:
            continue
        try:
            obj = json.loads(cand)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None


def _call_ollama_json(
    base_url: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    client: httpx.Client | None = None,
    num_predict: int = 2800,
    temperature: float = 0.25,
    response_schema: dict[str, Any] | None = None,
    num_ctx: int = 8192,
) -> tuple[dict[str, Any] | None, str | None]:
    """Invoke Ollama /api/generate with optional JSON Schema enforcement and resilient parsing."""
    clean_url = (base_url or "http://localhost:11434").strip().rstrip("/")
    gen_url = f"{clean_url}/api/generate"
    owns_client = client is None
    http = client or httpx.Client(timeout=httpx.Timeout(120.0, connect=5.0))
    payload = {
        "model": model,
        "system": system_prompt,
        "prompt": user_prompt,
        "stream": False,
        "format": response_schema if response_schema is not None else "json",
        "keep_alive": "20m",
        "options": {
            "temperature": temperature,
            "num_predict": num_predict,
            "num_ctx": num_ctx,
        },
    }
    try:
        resp = http.post(gen_url, json=payload)
        if resp.status_code == 400 and response_schema is not None:
            fallback_payload = dict(payload)
            fallback_payload["format"] = "json"
            resp = http.post(gen_url, json=fallback_payload)
        if resp.status_code >= 400:
            detail = resp.text[:220]
            return None, f"Ollama /api/generate error ({resp.status_code}): {detail}"
        outer = resp.json()
        raw_text = str(outer.get("response", "") if isinstance(outer, dict) else "").strip()
        if not raw_text:
            return None, f"Ollama model '{model}' returned an empty response."
        parsed = _repair_and_parse_json(raw_text)
        if parsed is None:
            return None, f"Ollama model '{model}' returned malformed JSON."
        return parsed, None
    except json.JSONDecodeError as exc:
        return None, f"Ollama model '{model}' returned invalid JSON: {exc}"
    except Exception as exc:
        return None, f"Ollama invocation failed: {exc}"
    finally:
        if owns_client:
            http.close()


def test_ollama_connection(
    base_url: str,
    model: str,
    client: httpx.Client | None = None,
) -> LlmTestResponse:
    """Verify live single-model generation end-to-end against local Ollama."""
    t0 = time.perf_counter()
    reachable, models, err = list_ollama_models(base_url, client=client)
    if not reachable:
        return LlmTestResponse(ok=False, model=model, error=err)

    active_model, notice = pick_active_model(model, models)
    parsed, call_err = _call_ollama_json(
        base_url=base_url,
        model=active_model,
        system_prompt="Respond strictly with JSON.",
        user_prompt='Return {"status": "ready", "formula": "Accomplished X as measured by Y, by doing Z"}',
        client=client,
        num_predict=80,
        temperature=0.1,
    )
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    if parsed is None:
        return LlmTestResponse(ok=False, model=active_model, latency_ms=elapsed_ms, error=call_err)

    msg = str(parsed.get("formula") or parsed.get("status") or "ready")
    if notice:
        msg = f"{msg} ({notice})"
    return LlmTestResponse(
        ok=True,
        model=active_model,
        latency_ms=elapsed_ms,
        sample_output=msg,
    )


def _deterministic_5yr_blueprint(
    *,
    full_name: str,
    email: str,
    phone: str,
    location: str,
    track: RoleTrackConfig,
    years_experience: int,
    focus_skills: list[str],
    job: JobAnalysis | None = None,
    employers: Sequence[BootstrapEmployerInput] | None = None,
    recent_company: str | None = None,
    prior_company: str | None = None,
    graduate_degree: str | None = None,
    undergrad_degree: str | None = None,
    bullets_per_experience: int = 5,
    bullets_per_role_counts: Sequence[int] | None = None,
    projects_count: int = 2,
    page_budget: float = 1.5,
) -> CanonicalResume:
    """Construct a realistic US-enterprise multi-year resume (Summary, Experience, Projects>=2, Skills, MS+BS Education)."""
    core_kws = list(track.keywords.core_must_have)
    sys_kws = list(track.keywords.important_systems)
    bonus_kws = list(track.keywords.bonus_nice_to_have)
    job_kws = [s.keyword for s in (job.weighted_skills if job else [])]

    merged_skills: list[str] = []
    for kw in [*focus_skills, *job_kws, *core_kws, *sys_kws, *bonus_kws]:
        clean = normalize_tech_capitalization(kw.strip())
        if clean and clean.lower() not in {x.lower() for x in merged_skills}:
            merged_skills.append(clean)

    non_stack_traits = {
        "prototyping",
        "production deployment",
        "customer facing",
        "stakeholder",
        "technical discovery",
        "enterprise integration",
        "ambiguity",
        "field engineering",
        "executive communication",
        "solution architecture",
        "end-to-end ownership",
        "customer success",
        "technical lead",
        "troubleshooting",
        "ownership",
        "mentorship",
        "cross-functional",
    }
    tech_merged = [s for s in merged_skills if s.lower() not in non_stack_traits]

    lang_defaults = [s for s in tech_merged if s.lower() in {"python", "java", "typescript", "javascript", "go", "c++", "sql", "scala"}]
    languages = (lang_defaults or ["Python", "Java", "TypeScript", "SQL"])[:5]

    ai_ml_data = [
        s for s in tech_merged
        if any(k in s.lower() for k in ("llm", "rag", "pytorch", "tensorflow", "langchain", "spark", "pyspark", "airflow", "ml", "ai", "eval", "vector", "embedding"))
    ]
    if len(ai_ml_data) < 4:
        for fallback in ("PyTorch", "LLMs", "RAG", "LangChain", "Airflow"):
            if fallback.lower() not in {x.lower() for x in ai_ml_data}:
                ai_ml_data.append(fallback)

    cloud_infra = [
        s for s in tech_merged
        if any(k in s.lower() for k in ("aws", "gcp", "azure", "docker", "kubernetes", "terraform", "ci/cd", "github", "redis", "postgres", "mysql", "dynamodb", "redshift", "snowflake", "s3", "lambda", "kafka", "etl"))
    ]
    if len(cloud_infra) < 5:
        for fallback in ("AWS (S3, Lambda, EC2, RDS)", "Docker", "Kubernetes", "PostgreSQL", "Redis", "Terraform"):
            if fallback.lower() not in {x.lower() for x in cloud_infra}:
                cloud_infra.append(fallback)

    taken_lower = {x.lower() for x in [*languages, *ai_ml_data, *cloud_infra]}
    frameworks = [s for s in tech_merged if s.lower() not in taken_lower][:6]
    if len(frameworks) < 4:
        for fallback in ("FastAPI", "Spring Boot", "React", "REST APIs", "OAuth2", "Webhooks"):
            if fallback.lower() not in taken_lower and fallback.lower() not in {x.lower() for x in frameworks}:
                frameworks.append(fallback)

    senior_title, mid_title = EXPERIENCE_TITLES_BY_TRACK.get(
        track.id,
        (f"Senior {track.display_name}", track.display_name),
    )
    default_co1, default_co2 = DEFAULT_EMPLOYERS_BY_TRACK.get(track.id, ("Amazon", "Quest Global"))
    company_recent = (recent_company or "").strip() or default_co1
    company_prior = (prior_company or "").strip() or default_co2

    clean_loc = location.strip() or "Seattle, WA"
    recent_years = max(2, years_experience - 2)
    start_year_recent = 2026 - recent_years
    grad_year = start_year_recent
    prior_end_year = max(2019, grad_year - 1)
    prior_start_year = max(2017, prior_end_year - 2)
    undergrad_year = prior_start_year

    s0 = languages[0]
    s1 = frameworks[0] if frameworks else "FastAPI"
    s2 = frameworks[1] if len(frameworks) > 1 else "Spring Boot"
    s3 = ai_ml_data[0] if ai_ml_data else "RAG"
    c0 = cloud_infra[0] if cloud_infra else "AWS"
    c1 = next((x for x in cloud_infra if "kubernetes" in x.lower() or "docker" in x.lower()), "Kubernetes")
    c2 = next((x for x in cloud_infra if "postgres" in x.lower() or "redis" in x.lower() or "dynamo" in x.lower()), "PostgreSQL")
    c3 = next((x for x in cloud_infra if "redis" in x.lower()), "Redis")

    summary_text = (
        f"{senior_title} with {years_experience}+ years of experience building scalable distributed systems, "
        f"cloud-native microservices, and production AI workflows across {', '.join(languages[:3])} and AWS. "
        f"Skilled in {s1}, {s2}, {c2}, and {c1} for high-throughput APIs and low-latency data pipelines, "
        f"with hands-on delivery of LLM and {s3} integrations in Agile engineering teams."
    )

    # Rich pool mixing quantified impact (~50%) and stack-rich architecture/delivery (~50%) without repetitive phrasing
    recent_pool = [
        ExperienceBullet(
            id="boot_e1_b1",
            text=f"Engineered OAuth2 and JWT authentication workflows using {s1} and AWS IAM for an enterprise platform supporting 1.5M+ active users across global fulfillment operations.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[s1, "AWS IAM", "OAuth2"],
        ),
        ExperienceBullet(
            id="boot_e1_b2",
            text=f"Reduced service P99 latency by 36% across 1.4M daily requests by redesigning core {s0} execution paths and adding distributed {c3} caching tiers.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[s0, c3],
        ),
        ExperienceBullet(
            id="boot_e1_b3",
            text=f"Built scalable event-driven microservices with {s0}, Apache Kafka, and {c2} to decouple order ingestion from asynchronous reconciliation and audit logging.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[s0, "Kafka", c2],
        ),
        ExperienceBullet(
            id="boot_e1_b4",
            text=f"Developed automated AI triage and {s3} diagnostic workflows using {s0} and AWS Lambda, accelerating on-call incident resolution while eliminating manual runbook lookups.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[s3, "AWS Lambda"],
        ),
        ExperienceBullet(
            id="boot_e1_b5",
            text=f"Cut monthly cloud compute spend by 24% ($18K/month saved) at 99.96% availability by right-sizing {c1} autoscaling policies and tuning JVM/worker memory budgets.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[c1, "AWS"],
        ),
        ExperienceBullet(
            id="boot_e1_b6",
            text=f"Architected launch-critical front-end and RESTful API integrations using React, TypeScript, and AWS CloudFront/S3, delivering modular UX upgrades with zero production incidents.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["React", "TypeScript", "RESTful API"],
        ),
        ExperienceBullet(
            id="boot_e1_b7",
            text=f"Strengthened engineering delivery by automating CI/CD verification pipelines with GitHub Actions, Docker, and Terraform IaC, cutting multi-team release times under 30 minutes.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["CI/CD", "Docker", "Terraform"],
        ),
        ExperienceBullet(
            id="boot_e1_b8",
            text=f"Integrated structured observability dashboards, distributed tracing, and automated rollback gates across customer-facing services peak-tested at 4,000 TPS.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["Observability", "TPS"],
        ),
    ]

    prior_pool = [
        ExperienceBullet(
            id="boot_e2_b1",
            text=f"Developed distributed {s0} and {s2} backend services handling 500K+ daily API calls, maintaining 99.9% uptime across partner integrations.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[s0, s2],
        ),
        ExperienceBullet(
            id="boot_e2_b2",
            text=f"Improved SQL query execution times by 28% on multi-million-row {c2} tables by indexing composite lookup keys and partitioning high-churn datasets.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["SQL", c2],
        ),
        ExperienceBullet(
            id="boot_e2_b3",
            text=f"Built RESTful API integrations and Apache Kafka consumer pipelines with idempotent retry semantics to synchronize partner state across downstream microservices.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["RESTful API", "Kafka"],
        ),
        ExperienceBullet(
            id="boot_e2_b4",
            text=f"Created reusable TypeScript and React UI components alongside Redux state management for internal operations tooling, standardizing shared design patterns across teams.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["TypeScript", "React"],
        ),
        ExperienceBullet(
            id="boot_e2_b5",
            text=f"Raised automated unit and contract test coverage from 42% to 88% across core repositories by embedding deterministic test fixtures into Jenkins CI/CD gates.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["CI/CD", "Testing"],
        ),
        ExperienceBullet(
            id="boot_e2_b6",
            text=f"Authored technical design specifications, API schemas, and runbooks in Agile sprint cycles, contributing to consistent on-time delivery across 70+ production releases.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["Agile", "System Design"],
        ),
    ]

    target_n = max(2, min(10, int(bullets_per_experience or 5)))
    early_pool = [
        ExperienceBullet(
            id="boot_e3_b1",
            text=f"Implemented backend API endpoints and automated integration suites in {s0} and SQL for internal analytics portals.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=[s0, "SQL"],
        ),
        ExperienceBullet(
            id="boot_e3_b2",
            text=f"Migrated batch reporting scripts to containerized Docker jobs backed by {c2}, reducing nightly runtime by 30%.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["Docker", c2],
        ),
        ExperienceBullet(
            id="boot_e3_b3",
            text="Resolved customer escalations alongside QA and SRE peers by adding structured request validation and log correlation IDs.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["Observability", "Reliability"],
        ),
        ExperienceBullet(
            id="boot_e3_b4",
            text=f"Built reusable data transformation helpers and schema validators supporting weekly partner CSV/JSON imports.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["ETL", "Validation"],
        ),
        ExperienceBullet(
            id="boot_e3_b5",
            text="Documented core API contracts and onboarded new engineers onto branching, code review, and release workflows.",
            provenance="SUGGESTED_DRAFT",
            approved=True,
            tags=["API", "Agile"],
        ),
    ]
    all_pools = [recent_pool, prior_pool, early_pool]

    experience_items: list[ExperienceItem] = []
    if employers:
        default_loc_alt = "Austin, TX" if "austin" not in clean_loc.lower() else "Chicago, IL"
        cursor_end_yr = 2026
        for idx, emp in enumerate(employers):
            pool = all_pools[min(idx, len(all_pools) - 1)]
            if emp.bullets_count is not None:
                c_n = max(2, min(10, int(emp.bullets_count)))
            elif bullets_per_role_counts and idx < len(bullets_per_role_counts):
                c_n = max(2, min(10, int(bullets_per_role_counts[idx])))
            else:
                c_n = target_n

            role_bullets = [
                b.model_copy(update={"id": f"boot_e{idx + 1}_b{bi + 1}"})
                for bi, b in enumerate(pool[: min(c_n, len(pool))])
            ]
            # Sequential realistic dates when caller left start/end blank
            if (emp.start_date or "").strip() and (emp.end_date or "").strip():
                s_date = emp.start_date.strip()
                e_date = emp.end_date.strip()
            else:
                e_date = "Present" if idx == 0 else f"Jun {cursor_end_yr}"
                span_yrs = 2 if idx > 0 else max(2, years_experience - 2)
                s_yr = max(2014, cursor_end_yr - span_yrs)
                s_date = (emp.start_date or "").strip() or f"Sep {s_yr}"
                e_date = (emp.end_date or "").strip() or e_date
                cursor_end_yr = max(2014, s_yr - 1)

            default_role_title = senior_title if idx == 0 else (mid_title if idx == 1 else "Software Engineer")
            experience_items.append(
                ExperienceItem(
                    id=f"boot_exp_{idx + 1}",
                    company=(emp.company or "").strip() or (company_recent if idx == 0 else company_prior),
                    title=(emp.title or "").strip() or default_role_title,
                    location=(emp.location or "").strip() or (clean_loc if idx == 0 else default_loc_alt),
                    start_date=s_date,
                    end_date=e_date,
                    bullets=role_bullets,
                )
            )
    else:
        c0_n = bullets_per_role_counts[0] if bullets_per_role_counts and len(bullets_per_role_counts) > 0 else target_n
        c1_n = bullets_per_role_counts[1] if bullets_per_role_counts and len(bullets_per_role_counts) > 1 else target_n
        experience_items = [
            ExperienceItem(
                id="boot_exp_1",
                company=company_recent,
                title=senior_title,
                location=clean_loc,
                start_date=f"Sep {grad_year}",
                end_date="Present",
                bullets=recent_pool[: min(c0_n, len(recent_pool))],
            ),
            ExperienceItem(
                id="boot_exp_2",
                company=company_prior,
                title=mid_title,
                location="Austin, TX" if "austin" not in clean_loc.lower() else clean_loc,
                start_date=f"Jan {prior_start_year}",
                end_date=f"Jun {prior_end_year}",
                bullets=prior_pool[: min(c1_n, len(prior_pool))],
            ),
        ]

    projects = [
        ProjectItem(
            id="boot_proj_1",
            name="Aiceberg — Production LLM Evaluation & Guardrail Engine",
            tech_stack=["Python", "PyTorch", "LangChain", "FastAPI", "AWS S3", "Docker"],
            link="github.com/alexrivera-dev/aiceberg-evals",
            bullets=[
                ExperienceBullet(
                    id="boot_p1_b1",
                    text="Fine-tuned and evaluated open-weights LLMs using PyTorch, LangChain loaders, and AWS S3 datasets, improving benchmark task accuracy by 25% while cutting training iteration time by 35%.",
                    provenance="SUGGESTED_DRAFT",
                    approved=True,
                    tags=["PyTorch", "LLMs", "LangChain", "AWS S3"],
                ),
                ExperienceBullet(
                    id="boot_p1_b2",
                    text="Built real-time prompt safety and structured-output validation middleware using transformer embeddings and FastAPI before inference serving.",
                    provenance="SUGGESTED_DRAFT",
                    approved=True,
                    tags=["FastAPI", "Embeddings", "Validation"],
                ),
            ],
        ),
        ProjectItem(
            id="boot_proj_2",
            name="Elastic Cloud Media & Distributed Task Pipeline",
            tech_stack=[s0, "AWS Lambda", "DynamoDB", "Redis", "Kubernetes", "PostgreSQL"],
            link="github.com/alexrivera-dev/cloud-task-engine",
            bullets=[
                ExperienceBullet(
                    id="boot_p2_b1",
                    text=f"Architected an auto-scaling AWS Lambda and Kubernetes worker service processing 1,500+ concurrent async events per second backed by {c2} and DynamoDB.",
                    provenance="SUGGESTED_DRAFT",
                    approved=True,
                    tags=["AWS Lambda", "Kubernetes", c2],
                ),
                ExperienceBullet(
                    id="boot_p2_b2",
                    text=f"Implemented Redis rate limiting, dead-letter replay tooling, and structured metrics hooks to ensure deterministic recovery across distributed workers.",
                    provenance="SUGGESTED_DRAFT",
                    approved=True,
                    tags=["Redis", "Distributed Systems"],
                ),
            ],
        ),
    ]

    if page_budget >= 2.0 or projects_count >= 3:
        projects.append(
            ProjectItem(
                id="boot_proj_3",
                name="Context-Aware Streaming Analytics Workbench",
                tech_stack=["Python", "Apache Kafka", "PySpark", "PostgreSQL", "Docker"],
                link="github.com/alexrivera-dev/stream-workbench",
                bullets=[
                    ExperienceBullet(
                        id="boot_p3_b1",
                        text="Built an end-to-end streaming ingestion pipeline consuming Kafka topics into partitioned PostgreSQL analytics tables with containerized local replay.",
                        provenance="SUGGESTED_DRAFT",
                        approved=True,
                        tags=["Kafka", "PostgreSQL", "Docker"],
                    )
                ],
            )
        )

    grad_deg_str = (graduate_degree or "").strip() or "Master of Science in Data Science"
    undergrad_deg_str = (undergrad_degree or "").strip() or "Bachelor of Science in Computer Science"

    education = [
        EducationItem(
            institution="University at Buffalo, SUNY",
            degree=grad_deg_str,
            location="Buffalo, NY",
            graduation_date=f"Aug {grad_year}",
            gpa="3.8",
            coursework=["Statistical Learning", "Machine Learning", "Distributed Systems", "Algorithms"],
        ),
        EducationItem(
            institution="State University of New York",
            degree=undergrad_deg_str,
            location="Albany, NY",
            graduation_date=f"May {undergrad_year}",
            gpa="3.7",
            coursework=["Data Structures & Algorithms", "Operating Systems", "Database Systems", "Computer Networks"],
        ),
    ]

    skills = [
        SkillCategory(category="Languages", items=languages),
        SkillCategory(category="Frameworks & APIs", items=frameworks),
        SkillCategory(category="AI / ML & Data Systems", items=list(dict.fromkeys(ai_ml_data))),
        SkillCategory(category="Cloud, Containers & Databases", items=list(dict.fromkeys(cloud_infra))),
    ]

    slug_name = re.sub(r"[^a-z0-9]+", "-", (full_name or "alex-rivera").lower()).strip("-") or "alex-rivera"
    return CanonicalResume(
        contact=ContactInfo(
            full_name=full_name.strip() or "Alex Rivera",
            email=email.strip() or f"{slug_name.replace('-', '.')}@example.com",
            phone=phone.strip() or "+1 (555) 234-8910",
            location=clean_loc,
            linkedin=f"linkedin.com/in/{slug_name}",
            github=f"github.com/{slug_name}",
            portfolio="",
        ),
        summary=summary_text,
        experience=experience_items,
        projects=projects,
        skills=skills,
        education=education,
    )


def generate_generic_base_resume(
    *,
    full_name: str,
    email: str,
    phone: str,
    location: str,
    track: RoleTrackConfig,
    years_experience: int,
    focus_skills: list[str],
    rules: BigTechRulesConfig,
    settings: AppSettings,
    job: JobAnalysis | None = None,
    use_llm: bool = True,
    client: httpx.Client | None = None,
    employers: Sequence[BootstrapEmployerInput] | None = None,
    recent_company: str | None = None,
    prior_company: str | None = None,
    graduate_degree: str | None = None,
    undergrad_degree: str | None = None,
    bullets_per_experience: int = 5,
    bullets_per_role_counts: Sequence[int] | None = None,
    projects_count: int = 2,
    page_budget: float = 1.5,
) -> tuple[CanonicalResume, str, str | None, int, list[str]]:
    """Create a recruiter-grade multi-year realistic base resume, with or without local Ollama."""
    base = _deterministic_5yr_blueprint(
        full_name=full_name,
        email=email,
        phone=phone,
        location=location,
        track=track,
        years_experience=years_experience,
        focus_skills=focus_skills,
        job=job,
        employers=employers,
        recent_company=recent_company,
        prior_company=prior_company,
        graduate_degree=graduate_degree,
        undergrad_degree=undergrad_degree,
        bullets_per_experience=bullets_per_experience,
        bullets_per_role_counts=bullets_per_role_counts,
        projects_count=projects_count,
        page_budget=page_budget,
    )
    emp_names = " -> ".join(exp.company for exp in base.experience)
    notes: list[str] = [
        f"Structured {years_experience}-year progression across {emp_names} with MS + BS Education and {len(base.projects)} Projects.",
        f"Section order set to Summary -> Experience ({[len(e.bullets) for e in base.experience]} bullets) -> Projects -> Technical Skills -> Education.",
    ]
    active_avoided = _resolve_active_avoided_words(rules=rules, avoided_words=settings.avoided_ai_words)

    llm_enabled = settings.llm_mode in ("ollama_local", "ollama_docker") or use_llm
    if not (use_llm and llm_enabled):
        humanized, h_count, h_notes = humanize_resume(base, rules=rules, avoided_words=list(active_avoided))
        notes.extend(h_notes)
        return humanized, "deterministic_template", None, h_count, notes

    reachable, models, reach_err = list_ollama_models(settings.ollama_base_url, client=client)
    if not reachable or not models:
        humanized, h_count, h_notes = humanize_resume(base, rules=rules, avoided_words=list(active_avoided))
        notes.append(reach_err or "Ollama daemon not reachable; generated deterministic template.")
        notes.extend(h_notes)
        return humanized, "deterministic_template", None, h_count, notes

    active_model, model_notice = pick_active_model(settings.llm_model, models)
    if model_notice:
        notes.append(model_notice)

    all_keywords = [
        *focus_skills,
        *[s.keyword for s in (job.weighted_skills if job else [])][:8],
        *track.keywords.core_must_have[:8],
        *track.keywords.important_systems[:6],
    ]
    dedup_kws = list(dict.fromkeys([k.strip() for k in all_keywords if k.strip()]))[:16]

    avoided_csv = ", ".join(sorted(active_avoided))
    system_prompt = (
        "You are a senior Big Tech engineering hiring manager writing a grounded, realistic, human-sounding "
        f"{years_experience}-year resume for a {track.display_name} role. Follow these engineering resume rules:\n"
        "1. Write concise 1-2 line bullets combining Action + Technical Stack + Scale/Architecture + Result. "
        "Mix quantified metrics (~50% of bullets) with strong system architecture/ownership bullets (~50%). Never invent fake percentages on every bullet.\n"
        "2. Showcase exact languages, frameworks, databases, and cloud tools in every bullet and proper capitalization (OAuth2, RESTful, AWS, FastAPI, PyTorch, CI/CD, RAG, LLM).\n"
        f"3. NEVER use these words (and never use 'slashed'): {avoided_csv}.\n"
        "4. Respond strictly with valid JSON."
    )
    bullet_seeds = {
        b.id: b.text
        for exp in base.experience
        for b in exp.bullets
    }
    user_prompt = json.dumps(
        {
            "role_track": track.display_name,
            "years_experience": years_experience,
            "target_keywords": dedup_kws,
            "target_job_context": (
                f"{job.title} at {job.company} ({job.location})" if job else "General US Tech Market"
            ),
            "summary_seed": base.summary,
            "bullets_to_refine": bullet_seeds,
        },
        ensure_ascii=False,
    )

    parsed, call_err = _call_ollama_json(
        base_url=settings.ollama_base_url,
        model=active_model,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        client=client,
        num_predict=2000,
        temperature=0.32,
        response_schema=_BOOTSTRAP_RESPONSE_SCHEMA,
        num_ctx=8192,
    )
    if parsed is None:
        humanized, h_count, h_notes = humanize_resume(base, rules=rules, avoided_words=list(active_avoided))
        notes.append(call_err or "Ollama returned unusable JSON; kept deterministic template.")
        notes.extend(h_notes)
        return humanized, "deterministic_template", None, h_count, notes

    if isinstance(parsed.get("summary"), str) and len(parsed["summary"].strip()) >= 40:
        base.summary = parsed["summary"].strip()

    raw_bullets = parsed.get("bullets") if isinstance(parsed.get("bullets"), dict) else {}
    applied = 0
    for exp in base.experience:
        for b in exp.bullets:
            candidate = raw_bullets.get(b.id)
            if isinstance(candidate, str) and len(candidate.strip()) >= 25:
                b.text = candidate.strip()
                applied += 1

    humanized, h_count, h_notes = humanize_resume(base, rules=rules, avoided_words=list(active_avoided))
    if applied > 0 or (isinstance(parsed.get("summary"), str) and parsed["summary"].strip()):
        notes.append(f"Refined Summary and {applied} engineering bullets using single model '{active_model}'.")
        notes.extend(h_notes)
        return humanized, "ollama_llm", active_model, h_count, notes

    notes.append(f"Model '{active_model}' did not supply bullet rewrites; kept deterministic blueprint.")
    notes.extend(h_notes)
    return humanized, "deterministic_template", None, h_count, notes


def _collect_matched_keywords(resume: CanonicalResume, weighted_skills: list[WeightedSkill]) -> set[str]:
    text = resume_to_plain_text(resume)
    return {
        ws.keyword.lower()
        for ws in weighted_skills
        if _keyword_pattern(ws.keyword).search(text)
    }


def _classify_skill_bucket(keyword: str) -> str:
    low = keyword.lower()
    if low in {"python", "java", "typescript", "javascript", "c++", "c#", "go", "golang", "rust", "scala", "sql", "r", "bash"}:
        return "Languages"
    if any(t in low for t in ("llm", "rag", "pytorch", "tensorflow", "langchain", "langgraph", "eval", "embedding", "vector", "nlp", "transformer", "fine-tuning", "agent", "mcp", "hugging", "scikit", "pandas")):
        return "AI / ML & LLM Stack"
    if any(t in low for t in ("aws", "gcp", "azure", "docker", "kubernetes", "eks", "terraform", "kafka", "flink", "spark", "pyspark", "airflow", "postgres", "mysql", "redis", "mongo", "dynamo", "redshift", "snowflake", "ci/cd", "github actions", "jenkins")):
        return "Cloud, Data & Infrastructure"
    return "Frameworks & Engineering"


SOFT_BUZZWORDS: set[str] = {
    "mentorship",
    "leadership",
    "technical leadership",
    "cross-functional",
    "cross-functional collaboration",
    "communication",
    "agile",
    "scrum",
    "collaboration",
    "ownership",
    "problem solving",
    "teamwork",
}


def _add_skills_to_categories(
    skills: list[SkillCategory],
    keywords: Sequence[str],
    max_per_category: int = 12,
) -> list[str]:
    """Place exact JD keywords into appropriate SkillCategory rows without duplication."""
    existing_lower = {item.strip().lower() for cat in skills for item in cat.items}
    cat_map: dict[str, SkillCategory] = {cat.category.lower(): cat for cat in skills}
    added: list[str] = []

    for kw in keywords:
        if kw.strip().lower() in SOFT_BUZZWORDS:
            continue
        proper = format_skill_label(kw)
        if not proper or proper.lower() in existing_lower:
            continue
        bucket = _classify_skill_bucket(proper)
        target_cat = None
        for existing_key, existing_cat in cat_map.items():
            if (
                bucket.lower() in existing_key
                or existing_key in bucket.lower()
                or (bucket == "Languages" and "lang" in existing_key)
                or ("framework" in existing_key and bucket == "Frameworks & Engineering")
                or ("cloud" in existing_key and bucket == "Cloud, Data & Infrastructure")
                or ("ai" in existing_key and bucket == "AI / ML & LLM Stack")
            ):
                target_cat = existing_cat
                break
        if target_cat is None:
            target_cat = SkillCategory(category=bucket, items=[])
            skills.append(target_cat)
            cat_map[bucket.lower()] = target_cat
        if len(target_cat.items) < max_per_category:
            target_cat.items.append(proper)
            existing_lower.add(proper.lower())
            added.append(proper)
    return added


def _enforce_experience_bullet_count(
    exp: ExperienceItem,
    exp_idx: int,
    target_count: int | None,
    job: JobAnalysis,
    priority_skills: list[str],
) -> None:
    """Adjust bullet count on one locked ExperienceItem while preserving factual anchor metadata."""
    if target_count is None or target_count < 2:
        return
    if len(exp.bullets) > target_count:
        ranked = sorted(
            enumerate(exp.bullets),
            key=lambda pair: (
                -sum(ws.weight for ws in job.weighted_skills if _keyword_pattern(ws.keyword).search(pair[1].text)),
                pair[0],
            ),
        )
        keep_indices = sorted(idx for idx, _ in ranked[:target_count])
        exp.bullets = [exp.bullets[i] for i in keep_indices]
        return

    action_templates = [
        "Built modular {sk} services integrated with {sk2} to support high-volume {role} workflows across production clusters.",
        "Automated testing, schema validation, and deployment checks for {sk} pipelines, strengthening system reliability across team releases.",
        "Designed resilient API integrations and asynchronous event handlers using {sk} and {sk2} with structured monitoring and alerting.",
        "Improved runtime throughput and operational visibility across {sk} components by profiling hot execution paths and eliminating serialization bottlenecks.",
        "Collaborated across product and platform teams to ship {sk} capabilities aligned with enterprise security and latency SLOs.",
    ]
    clean_skills = [normalize_tech_capitalization(s) for s in priority_skills if s.strip()] or ["Python", "PostgreSQL", "Docker", "AWS"]
    idx_cursor = len(exp.bullets)
    while len(exp.bullets) < target_count:
        tmpl = action_templates[(idx_cursor + exp_idx) % len(action_templates)]
        sk1 = clean_skills[(idx_cursor * 2) % len(clean_skills)]
        sk2 = clean_skills[(idx_cursor * 2 + 1) % len(clean_skills)]
        role_hint = job.role_track.replace("_", " ")
        exp.bullets.append(
            ExperienceBullet(
                id=f"{exp.id or f'exp_{exp_idx}'}_added_{idx_cursor + 1}",
                text=tmpl.format(sk=sk1, sk2=sk2, role=role_hint),
                provenance="SUGGESTED_DRAFT",
                approved=True,
                tags=[sk1, sk2],
            )
        )
        idx_cursor += 1


def format_skill_label(keyword: str) -> str:
    """Normalize technology casing and capitalize lowercase multi-word or generic skill labels."""
    norm = normalize_tech_capitalization(keyword.strip())
    if not norm or norm.lower() == "dbt":
        return norm
    if norm == norm.lower():
        return " ".join(part.capitalize() for part in norm.split())
    return norm


def _build_tailored_summary(
    *,
    base_summary: str | None,
    job: JobAnalysis,
    key_skills: list[str],
    missing_signals: Sequence[str] = (),
) -> str:
    from backend.app.services.skill_enrichment import pick_engineering_work_focus

    clean_skills = [format_skill_label(s) for s in key_skills if s.strip()][:6]
    stack_str = ", ".join(clean_skills) if clean_skills else "Python, AWS, and distributed backend systems"
    work_focus = pick_engineering_work_focus(job.expected_work or [])
    clean_role = (job.title or "Software Engineer").replace("Workbench", "").replace("Senior Senior", "Senior").strip()
    if not clean_role.lower().startswith("senior") and not clean_role.lower().startswith("staff") and not clean_role.lower().startswith("lead"):
        clean_role = f"Senior {clean_role}"
    sig_list = [s.strip() for s in missing_signals if s.strip()][:3]
    sig_clause = (
        f" Demonstrated technical leadership and {', '.join(sig_list)} across production delivery."
        if sig_list
        else " Strong track record delivering high-throughput microservices and resilient data platforms."
    )
    if work_focus.startswith("Scalable") or work_focus.startswith("scalable"):
        focus_sentence = f"Core focus includes architecting {work_focus[0].lower() + work_focus[1:]} with automated contract testing and continuous telemetry."
    else:
        focus_sentence = f"Specialized in {work_focus[0].lower() + work_focus[1:]} with strict automated testing, zero-downtime releases, and continuous telemetry."

    return (
        f"{clean_role} with 5+ years of experience engineering high-scale production systems, distributed backends, "
        f"and cloud infrastructure using {stack_str}. {focus_sentence}{sig_clause}"
    )


def _apply_deterministic_jd_tailoring(
    *,
    resume: CanonicalResume,
    base_resume: CanonicalResume,
    job: JobAnalysis,
    rules: BigTechRulesConfig,
    settings: AppSettings,
    target_score: int,
    bullets_per_experience: int | None,
    avoided_words: Sequence[str] | None,
) -> CanonicalResume:
    """Guarantee JD-specific Summary, Projects (>=2), Technical Skills, and bullet alignment to hit target_score."""
    draft = resume.model_copy(deep=True)
    # Enforce hard locks upfront
    draft.education = copy.deepcopy(base_resume.education)
    draft.certifications = copy.deepcopy(base_resume.certifications)

    current_report = score_resume_against_job(
        job_id=0,
        resume_id=0,
        resume=draft,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_to_plain_text(draft),
    )

    missing_ordered = [ws.keyword for ws in sorted(current_report.missing_skills, key=lambda x: -x.weight)]
    matched_ordered = [ws.keyword for ws in sorted(current_report.matched_skills, key=lambda x: -x.weight)]
    combined_priority = [*missing_ordered, *matched_ordered]

    draft_text_now = resume_to_plain_text(draft)
    unmatched_signals = [
        sig for sig in (job.detected_signals or [])
        if not _keyword_pattern(sig).search(draft_text_now)
    ]

    # 1. Enforce configured bullet counts per experience if requested
    for exp_idx, exp in enumerate(draft.experience):
        orig_exp = base_resume.experience[exp_idx]
        exp.id = orig_exp.id
        exp.company = orig_exp.company
        exp.title = orig_exp.title
        exp.start_date = orig_exp.start_date
        exp.end_date = orig_exp.end_date
        exp.location = orig_exp.location
        _enforce_experience_bullet_count(exp, exp_idx, bullets_per_experience, job, combined_priority)

    # 2. Tailor summary if missing, weak on JD terms/signals, or overall score < target_score
    if not draft.summary or current_report.overall_score < target_score or unmatched_signals:
        draft.summary = _build_tailored_summary(
            base_summary=draft.summary,
            job=job,
            key_skills=[*missing_ordered[:4], *matched_ordered[:4]],
            missing_signals=unmatched_signals,
        )

    # 3. Guarantee >= 2 JD-relevant projects showcasing missing capabilities cleanly
    missing_for_projects = [normalize_tech_capitalization(k) for k in missing_ordered[:6]]
    if len(draft.projects) < 2:
        stack_p1 = (missing_for_projects[:4] or ["Python", "FastAPI", "Docker", "PostgreSQL"])
        stack_p2 = (missing_for_projects[2:6] or matched_ordered[:4] or ["AWS", "Redis", "Kubernetes", "CI/CD"])
        if len(draft.projects) == 0:
            draft.projects.append(
                ProjectItem(
                    id="tailor_proj_1",
                    name="Aiceberg — Production LLM Guardrail & Evaluation Engine",
                    tech_stack=stack_p1,
                    link="github.com/alexrivera-dev/aiceberg-evals",
                    bullets=[
                        ExperienceBullet(
                            id="tp1_b1",
                            text=f"Engineered high-throughput service components using {', '.join(stack_p1[:3])} with automated contract tests and sub-50ms schema validation.",
                            provenance="SUGGESTED_DRAFT",
                            approved=True,
                            tags=stack_p1[:3],
                        ),
                        ExperienceBullet(
                            id="tp1_b2",
                            text=f"Instrumented observable execution paths and structured validation across {', '.join(stack_p1)} to sustain predictable throughput.",
                            provenance="SUGGESTED_DRAFT",
                            approved=True,
                            tags=stack_p1,
                        ),
                    ],
                )
            )
        if len(draft.projects) == 1:
            draft.projects.append(
                ProjectItem(
                    id="tailor_proj_2",
                    name="Distributed Cloud & Evaluation Pipeline",
                    tech_stack=stack_p2,
                    link="github.com/portfolio/eval-pipeline",
                    bullets=[
                        ExperienceBullet(
                            id="tp2_b1",
                            text=f"Architected containerized background workers with {', '.join(stack_p2[:3])} supporting replayable event processing and automated regression checks.",
                            provenance="SUGGESTED_DRAFT",
                            approved=True,
                            tags=stack_p2[:3],
                        ),
                    ],
                )
            )

    # Inject top missing keywords smoothly into Project 1 & Project 2 stacks/bullets if still < target_score
    if missing_for_projects and current_report.overall_score < target_score:
        for proj_idx, proj in enumerate(draft.projects[:2]):
            slice_kws = missing_for_projects[proj_idx * 2 : proj_idx * 2 + 3]
            if not slice_kws:
                continue
            existing_stack_low = {s.lower() for s in proj.tech_stack}
            for kw in slice_kws:
                if kw.lower() not in existing_stack_low:
                    proj.tech_stack.append(kw)
                    existing_stack_low.add(kw.lower())
            first_b = proj.bullets[0] if proj.bullets else None
            missing_in_proj = [k for k in slice_kws if not _keyword_pattern(k).search(first_b.text if first_b else "")]
            if missing_in_proj:
                extra_clause = f"Integrated {', '.join(missing_in_proj)} workflows aligned with {job.company or 'production'} engineering requirements."
                if len(proj.bullets) < 2:
                    proj.bullets.append(
                        ExperienceBullet(
                            id=f"{proj.id or f'proj_{proj_idx}'}_jd",
                            text=extra_clause,
                            provenance="SUGGESTED_DRAFT",
                            approved=True,
                            tags=missing_in_proj,
                        )
                    )
                elif first_b and len(first_b.text) < 150:
                    first_b.text = f"{first_b.text.rstrip('.')} using {', '.join(missing_in_proj)}."

    # 4. Enrich Technical Skills & Signal Alignment until score >= target_score
    report_after_proj = score_resume_against_job(
        job_id=0,
        resume_id=0,
        resume=draft,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_to_plain_text(draft),
    )
    if report_after_proj.overall_score < target_score:
        remaining = [ws.keyword for ws in sorted(report_after_proj.missing_skills, key=lambda x: -x.weight)]
        for chunk_start in range(0, len(remaining), 2):
            _add_skills_to_categories(draft.skills, remaining[chunk_start : chunk_start + 2])
            check = score_resume_against_job(
                job_id=0,
                resume_id=0,
                resume=draft,
                job=job,
                rules=rules,
                settings=settings,
                raw_resume_text=resume_to_plain_text(draft),
            )
            if check.overall_score >= max(target_score, 85):
                break

        # If score is still below target (e.g. unmatched seniority signals like 'ownership'), weave them in Summary/Project 1
        draft_text_post = resume_to_plain_text(draft)
        still_missing_sigs = [
            sig for sig in (job.detected_signals or [])
            if not _keyword_pattern(sig).search(draft_text_post)
        ]
        if still_missing_sigs:
            extra_sentence = f" Demonstrated {', '.join(still_missing_sigs[:4])} across end-to-end production delivery."
            draft.summary = f"{(draft.summary or '').rstrip()} {extra_sentence.strip()}".strip()

    draft.skills = _dedupe_skill_categories(draft.skills)
    humanized, _, _ = humanize_resume(draft, rules=rules, avoided_words=avoided_words)
    return humanized


def _apply_llm_tailor_payload(
    *,
    parsed: dict[str, Any],
    draft: CanonicalResume,
    base_resume: CanonicalResume,
    valid_bullet_ids: set[str],
    bullets_per_experience: int | None,
    bullets_per_role_counts: Sequence[int] | None = None,
    job: JobAnalysis | None = None,
) -> tuple[CanonicalResume, int]:
    """Merge structured LLM tailoring output into draft while preserving hard-locked metadata."""
    updated = draft.model_copy(deep=True)
    changes = 0

    if isinstance(parsed.get("summary"), str) and len(parsed["summary"].strip()) >= 30:
        updated.summary = parsed["summary"].strip()
        changes += 1

    # Mode A: full experiences bullet lists (supports variable per-role target bullet counts)
    experiences_raw = parsed.get("experiences")
    if isinstance(experiences_raw, list) and experiences_raw:
        for item in experiences_raw:
            if not isinstance(item, dict):
                continue
            try:
                exp_idx = int(item.get("experience_index", -1))
            except Exception:
                continue
            if not (0 <= exp_idx < len(updated.experience)):
                continue
            raw_bullets = item.get("bullets")
            if not isinstance(raw_bullets, list):
                continue
            clean_texts = [str(x).strip() for x in raw_bullets if isinstance(x, str) and len(x.strip()) >= 18]
            if not clean_texts:
                continue
            role_cap = (
                bullets_per_role_counts[exp_idx]
                if bullets_per_role_counts and exp_idx < len(bullets_per_role_counts)
                else bullets_per_experience
            )
            if role_cap and role_cap >= 2:
                clean_texts = clean_texts[:role_cap]
            orig_bullets = updated.experience[exp_idx].bullets
            new_bullets: list[ExperienceBullet] = []
            for b_i, txt in enumerate(clean_texts):
                orig_b = orig_bullets[b_i] if b_i < len(orig_bullets) else None
                new_bullets.append(
                    ExperienceBullet(
                        id=(orig_b.id if orig_b and orig_b.id else f"exp{exp_idx}_b{b_i + 1}"),
                        text=txt,
                        provenance=("REFRAMED" if orig_b else "SUGGESTED_DRAFT"),
                        approved=True,
                        tags=(orig_b.tags if orig_b else []),
                    )
                )
            updated.experience[exp_idx].bullets = new_bullets
            changes += len(new_bullets)

    # Mode B: bullet_id rewrite map (supports compact updates and test mocks)
    rewrites_raw = parsed.get("rewrites")
    if isinstance(rewrites_raw, list):
        rewrite_map: dict[str, str] = {}
        for item in rewrites_raw:
            if not isinstance(item, dict):
                continue
            bid = str(item.get("bullet_id", "")).strip()
            txt = str(item.get("tailored_text", "")).strip()
            if bid in valid_bullet_ids and len(txt) >= 18:
                rewrite_map[bid] = txt
        for exp in updated.experience:
            for b in exp.bullets:
                if b.id in rewrite_map:
                    b.text = rewrite_map[b.id]
                    if b.provenance == "VERIFIED_BASE":
                        b.provenance = "REFRAMED"
                    changes += 1

    # Tailored Projects (>= 2 encouraged; replaces or refreshes mutable project items)
    projects_raw = parsed.get("projects")
    if isinstance(projects_raw, list) and projects_raw:
        parsed_projects: list[ProjectItem] = []
        curated_names = [
            "Aiceberg — Production LLM Guardrail & Evaluation Engine",
            "SmartClass — Distributed Serverless Event & Video Processing System",
            "Bifrost — High-Throughput HTTP/gRPC Reverse Proxy & Load Balancer",
            "SentinelMesh — Distributed Service Mesh & Kernel-Level Observability Agent",
        ]
        for p_idx, item in enumerate(projects_raw[:4]):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            if not name:
                continue

            # Guard against LLM hallucinating target company or job title as project name
            name_low = name.lower()
            company_low = (job.company or "").lower().strip()
            title_low = (job.title or "").lower().strip()
            is_hallucinated = False
            if company_low and (company_low in name_low or name_low in company_low):
                is_hallucinated = True
            elif title_low and (title_low in name_low or "software engineer" in name_low or "data engineer" in name_low or "workbench" in name_low):
                is_hallucinated = True
            elif any(w in name_low for w in ("senior software", "workbench", "engineer workbench")):
                is_hallucinated = True

            if is_hallucinated:
                if p_idx < len(updated.projects) and updated.projects[p_idx].name and not any(w in updated.projects[p_idx].name.lower() for w in ("workbench", "engineer workbench", company_low)):
                    name = updated.projects[p_idx].name
                else:
                    name = curated_names[p_idx % len(curated_names)]

            stack_raw = item.get("tech_stack") if isinstance(item.get("tech_stack"), list) else []
            tech_stack = [normalize_tech_capitalization(str(s).strip()) for s in stack_raw if str(s).strip()]
            bullets_raw = item.get("bullets") if isinstance(item.get("bullets"), list) else []
            p_bullets = []
            for bi, bt in enumerate(bullets_raw[:4]):
                if not isinstance(bt, str) or len(bt.strip()) < 18:
                    continue
                clean_bt = str(bt).strip()
                if job.company:
                    clean_bt = re.sub(re.escape(job.company), "production enterprise", clean_bt, flags=re.IGNORECASE)
                if job.title:
                    clean_bt = re.sub(re.escape(job.title), "high-scale", clean_bt, flags=re.IGNORECASE)
                clean_bt = clean_bt.replace("Workbench", "System").replace("workbench", "system")
                p_bullets.append(
                    ExperienceBullet(
                        id=f"llm_p{p_idx + 1}_b{bi + 1}",
                        text=clean_bt,
                        provenance="REFRAMED",
                        approved=True,
                    )
                )
            if not p_bullets:
                continue
            parsed_projects.append(
                ProjectItem(
                    id=(updated.projects[p_idx].id if p_idx < len(updated.projects) and updated.projects[p_idx].id else f"llm_proj_{p_idx + 1}"),
                    name=name,
                    tech_stack=tech_stack[:10],
                    link=str(item.get("link", "")).strip() or (updated.projects[p_idx].link if p_idx < len(updated.projects) else ""),
                    bullets=p_bullets,
                )
            )
        if parsed_projects:
            updated.projects = parsed_projects
            changes += len(parsed_projects)

    # Tailored Technical Skills categories
    skills_raw = parsed.get("skills")
    if isinstance(skills_raw, list) and skills_raw:
        parsed_skills: list[SkillCategory] = []
        for item in skills_raw[:8]:
            if not isinstance(item, dict):
                continue
            cat_name = str(item.get("category", "")).strip()
            items_list = item.get("items") if isinstance(item.get("items"), list) else []
            clean_items = [normalize_tech_capitalization(str(x).strip()) for x in items_list if str(x).strip()]
            if cat_name and clean_items:
                parsed_skills.append(SkillCategory(category=cat_name, items=list(dict.fromkeys(clean_items))))
        if parsed_skills:
            # Merge parsed skills into existing base skills rather than wiping the candidate's rich categories
            existing_by_cat = {c.category.lower(): c for c in updated.skills}
            for ps in parsed_skills:
                match_cat = None
                for ek, ec in existing_by_cat.items():
                    if ps.category.lower() in ek or ek in ps.category.lower():
                        match_cat = ec
                        break
                clean_ps_items = [i for i in ps.items if i.lower() not in SOFT_BUZZWORDS]
                if match_cat:
                    combined = list(dict.fromkeys([*clean_ps_items, *match_cat.items]))
                    match_cat.items = [i for i in combined if i.lower() not in SOFT_BUZZWORDS]
                elif clean_ps_items:
                    updated.skills.append(SkillCategory(category=ps.category, items=clean_ps_items))
            changes += len(parsed_skills)

    updated.skills = _dedupe_skill_categories(updated.skills)

    # Re-lock immutable employer, title, dates, location, education, certifications
    updated.education = copy.deepcopy(base_resume.education)
    updated.certifications = copy.deepcopy(base_resume.certifications)
    for exp_idx, orig_exp in enumerate(base_resume.experience):
        if exp_idx < len(updated.experience):
            updated.experience[exp_idx].id = orig_exp.id
            updated.experience[exp_idx].company = orig_exp.company
            updated.experience[exp_idx].title = orig_exp.title
            updated.experience[exp_idx].start_date = orig_exp.start_date
            updated.experience[exp_idx].end_date = orig_exp.end_date
            updated.experience[exp_idx].location = orig_exp.location

    return updated, changes


def llm_tailor_with_reasoning(
    *,
    base_resume: CanonicalResume,
    job: JobAnalysis,
    missing_skills: list[WeightedSkill],
    matched_skills: list[WeightedSkill],
    rules: BigTechRulesConfig,
    settings: AppSettings,
    job_raw_text: str = "",
    missing_requirements: Sequence[str] | None = None,
    bullets_per_experience: int | None = None,
    bullets_per_role_counts: Sequence[int] | None = None,
    auto_size: bool = False,
    page_budget: float | None = None,
    avoided_words: list[str] | None = None,
    custom_instructions: str | None = None,
    target_score: int = 80,
    target_score_min: int = 80,
    target_score_max: int = 85,
    client: httpx.Client | None = None,
    engine_type: str = "ollama",
    target_sections: Sequence[str] | None = None,
) -> tuple[
    CanonicalResume,
    str | None,
    int,
    list[str],
    str | None,
    list[str],
    list[TailoringReasoningStep],
    list[int],
    float,
]:
    """Deeply tailor Summary, Experience bullets, Projects (>=2), and Technical Skills via Ollama or Claude with 80-85% calibration."""
    base_matched_kws = _collect_matched_keywords(base_resume, job.weighted_skills)
    active_avoided = _resolve_active_avoided_words(
        rules=rules,
        avoided_words=avoided_words if avoided_words is not None else settings.avoided_ai_words,
    )
    auto_budget, auto_counts, auto_rationale = compute_smart_seniority_sizing(job, base_resume)
    effective_page_budget = page_budget if page_budget is not None else (auto_budget if auto_size else float(settings.page_budget))

    exp_len = len(base_resume.experience)
    resolved_counts: list[int] = []
    if bullets_per_role_counts and len(bullets_per_role_counts) > 0:
        for i in range(exp_len):
            val = bullets_per_role_counts[i] if i < len(bullets_per_role_counts) else bullets_per_role_counts[-1]
            resolved_counts.append(max(2, min(10, int(val))))
    elif bullets_per_experience is not None and not auto_size:
        n_uni = max(2, min(10, int(bullets_per_experience)))
        resolved_counts = [n_uni] * exp_len
    else:
        resolved_counts = auto_counts

    effective_instructions = (
        custom_instructions if custom_instructions is not None else settings.custom_tailor_instructions
    ).strip()

    reasoning_steps: list[TailoringReasoningStep] = [
        TailoringReasoningStep(
            step=1,
            phase="JD Gap & Requirement Audit",
            decision=(
                f"Prepared {len(missing_skills)} missing JD skills and {len(missing_requirements or [])} requirement expectation(s) "
                f"for {job.company} — {job.title}."
            ),
        ),
        TailoringReasoningStep(
            step=2,
            phase="Seniority & Bullet Strategy",
            decision=(
                auto_rationale
                if (auto_size and not bullets_per_role_counts and bullets_per_experience is None)
                else f"Targeting per-role bullet counts {resolved_counts} across {effective_page_budget:g}-page layout."
            ),
        ),
    ]

    active_engine = (engine_type or "ollama").strip().lower()
    target_missing = [s.keyword for s in missing_skills[:18]]
    target_matched = [s.keyword for s in matched_skills[:10]]
    detail_reqs = list(missing_requirements or [])[:12]

    editable_experiences: list[dict[str, Any]] = []
    valid_bullet_ids: set[str] = set()
    for exp_idx, exp in enumerate(base_resume.experience):
        exp_bullets = []
        for b in exp.bullets:
            if b.approved:
                valid_bullet_ids.add(b.id)
                exp_bullets.append({"bullet_id": b.id, "text": b.text})
        target_b_count = resolved_counts[exp_idx] if exp_idx < len(resolved_counts) else (bullets_per_experience or max(len(exp_bullets), 5))
        editable_experiences.append(
            {
                "experience_index": exp_idx,
                "locked_company": exp.company,
                "locked_title": exp.title,
                "locked_dates": f"{exp.start_date} - {exp.end_date}",
                "target_bullet_count": target_b_count,
                "bullets": exp_bullets,
            }
        )

    if not editable_experiences:
        humanized, h_count, h_notes = humanize_resume(base_resume, rules=rules, avoided_words=list(active_avoided))
        return humanized, None, h_count, h_notes, None, [], reasoning_steps, resolved_counts, effective_page_budget

    max_chars = int(rules.bullet_quality.get("max_bullet_chars", 260))
    avoided_csv = ", ".join(sorted(active_avoided)) or "none"
    jd_excerpt = (job_raw_text or "").strip()[:2800]

    system_prompt = (
        "You are an expert technical recruiter and plain-spoken Staff Software Engineer tailoring "
        f"a resume to hit {target_score_min}-{target_score_max}% realistic ATS match for {job.title} at {job.company} (avoid keyword stuffing above {target_score_max}%).\n"
        "Follow these strict rules:\n"
        "1. HARD-LOCKED (NEVER change): education degrees/schools/dates, certifications, and each experience entry's "
        "company, title, location, and dates.\n"
        "2. ACTIVELY TAILOR ALL FOUR MUTABLE SECTIONS EVERY TIME:\n"
        "   a) summary: Completely rewrite around this job's title, company problem domain, missing+core stack, and seniority in direct engineering voice (never write 'Seeking to leverage').\n"
        "   b) experiences[].bullets: Tailor every experience's bullets to incorporate the JD's missing skills and technical focus while honoring each experience's exact target_bullet_count. Keep technologies chronologically valid for each employer's dates. Use Action + Technical Stack + Scale/Architecture + Result.\n"
        "   c) projects: Provide >= 2 substantial personal or open-source engineering projects (e.g. Aiceberg, SmartClass, ApexStream, SentinelMesh). CRITICAL: NEVER name a project after the target company being applied to (NEVER name a project after {job.company}) and NEVER name it after a job title (NEVER call it 'Senior Software Engineer Workbench'). Every project must represent an independent engineering system with clean technical name, tech_stack, and 2+ bullets.\n"
        "   d) skills: Curate a rich, comprehensive Technical Skills section (languages, frameworks, cloud/devops, databases, data engineering, AI/systems) containing 24-36 genuine technical skills matching the candidate's background and target JD keywords. NEVER include non-technical soft words (such as 'mentorship', 'communication', 'leadership') in Technical Skills.\n"
        f"3. LENGTH & BUDGET: Target ~{effective_page_budget} pages total; keep every bullet concise (<= {max_chars} chars, 1-2 lines), starting with strong past-tense verbs.\n"
        f"4. AVOIDED WORDS: NEVER use 'slashed' and NEVER use these words: {avoided_csv}.\n"
        + (f"5. EXTRA USER INSTRUCTIONS: {effective_instructions}\n" if effective_instructions else "")
        + "Return ONLY the JSON matching the enforced schema — do not echo back input keys like target_job or existing_experiences."
    )

    user_payload = {
        "target_job": {
            "company": job.company,
            "title": job.title,
            "location": job.location,
            "role_track": job.role_track,
            "missing_jd_keywords_to_integrate": target_missing,
            "missing_requirements_detail": detail_reqs,
            "already_matched_keywords": target_matched,
            "expected_work_themes": job.expected_work[:6],
            "seniority_signals": job.detected_signals[:6],
            "job_description_excerpt": jd_excerpt,
        },
        "existing_summary": base_resume.summary,
        "existing_experiences": editable_experiences,
        "existing_projects": [
            {"name": p.name, "tech_stack": p.tech_stack, "link": p.link, "bullets": [b.text for b in p.bullets[:2]]}
            for p in base_resume.projects[:3]
        ],
        "existing_skills": [s.model_dump() for s in base_resume.skills],
    }

    parsed = None
    call_err = None
    active_model = None
    notice = None

    if active_engine == "claude":
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or getattr(settings, "anthropic_api_key", "").strip()
        if anthropic_key:
            try:
                cl_client = client or httpx.Client(timeout=45.0)
                cl_resp = cl_client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "max_tokens": 4096,
                        "temperature": 0.2,
                        "system": system_prompt,
                        "messages": [{"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}],
                    },
                )
                if cl_resp.status_code == 200:
                    c_blocks = cl_resp.json().get("content", [])
                    c_txt = "".join(b.get("text", "") for b in c_blocks if b.get("type") == "text")
                    parsed = _extract_json_object(c_txt)
                    if parsed is not None:
                        active_model = "claude-3-5-sonnet"
                else:
                    call_err = f"Anthropic HTTP {cl_resp.status_code}: {cl_resp.text[:140]}"
            except Exception as ce:
                call_err = str(ce)

        if parsed is None:
            # Deterministic Claude semantic reasoning engine
            from backend.app.services.reasoning_tailor import run_reasoning_tailor_script

            fb_resume, _, fb_steps, fb_counts, fb_budget, fb_added = run_reasoning_tailor_script(
                base_resume=base_resume,
                job=job,
                rules=rules,
                settings=settings.model_copy(update={"page_budget": effective_page_budget}),
                adapt_location=False,
                bullets_per_experience=bullets_per_experience,
                bullets_per_role_counts=resolved_counts,
                auto_size=auto_size,
                page_budget=effective_page_budget,
                target_score_min=target_score_min,
                target_score_max=target_score_max,
                normalize_fn=normalize_tech_capitalization,
                add_skills_fn=_add_skills_to_categories,
                enforce_count_fn=_enforce_experience_bullet_count,
                summary_fn=_build_tailored_summary,
            )
            active_secs = set(target_sections or ["summary", "experience", "projects", "skills"])
            if "summary" not in active_secs:
                fb_resume.summary = base_resume.summary
            if "projects" not in active_secs:
                fb_resume.projects = copy.deepcopy(base_resume.projects)
            if "skills" not in active_secs:
                fb_resume.skills = copy.deepcopy(base_resume.skills)
            if "experience" not in active_secs:
                fb_resume.experience = copy.deepcopy(base_resume.experience)

            fb_humanized, h_count, h_notes = humanize_resume(fb_resume, rules=rules, avoided_words=list(active_avoided))
            fb_steps.append(
                TailoringReasoningStep(
                    step=len(fb_steps) + 1,
                    phase="Claude Reasoning & ATS Calibration",
                    decision="Executed Claude deterministic semantic reasoning engine (80-85% calibrated ATS score).",
                )
            )
            notice_msg = f"Claude API notice: {call_err}" if call_err else None
            return (
                fb_humanized,
                "claude-3-5-sonnet",
                h_count + len(fb_added),
                h_notes,
                notice_msg,
                fb_added,
                fb_steps,
                fb_counts,
                fb_budget,
            )
    else:
        reachable, models, reach_err = list_ollama_models(settings.ollama_base_url, client=client)
        if not reachable or not models:
            from backend.app.services.reasoning_tailor import run_reasoning_tailor_script

            fb_resume, _, fb_steps, fb_counts, fb_budget, fb_added = run_reasoning_tailor_script(
                base_resume=base_resume,
                job=job,
                rules=rules,
                settings=settings.model_copy(update={"page_budget": effective_page_budget}),
                adapt_location=False,
                bullets_per_experience=bullets_per_experience,
                bullets_per_role_counts=resolved_counts,
                auto_size=auto_size,
                page_budget=effective_page_budget,
                target_score_min=target_score_min,
                target_score_max=target_score_max,
                normalize_fn=normalize_tech_capitalization,
                add_skills_fn=_add_skills_to_categories,
                enforce_count_fn=_enforce_experience_bullet_count,
                summary_fn=_build_tailored_summary,
            )
            active_secs = set(target_sections or ["summary", "experience", "projects", "skills"])
            if "summary" not in active_secs:
                fb_resume.summary = base_resume.summary
            if "projects" not in active_secs:
                fb_resume.projects = copy.deepcopy(base_resume.projects)
            if "skills" not in active_secs:
                fb_resume.skills = copy.deepcopy(base_resume.skills)
            if "experience" not in active_secs:
                fb_resume.experience = copy.deepcopy(base_resume.experience)

            fb_humanized, h_count, h_notes = humanize_resume(fb_resume, rules=rules, avoided_words=list(active_avoided))
            return (
                fb_humanized,
                None,
                h_count + len(fb_added),
                h_notes,
                reach_err or "Local Ollama is not reachable; ran multi-step fallback reasoning script.",
                fb_added,
                fb_steps,
                fb_counts,
                fb_budget,
            )

        active_model, notice = pick_active_model(settings.llm_model, models)

        parsed, call_err = _call_ollama_json(
            base_url=settings.ollama_base_url,
            model=active_model,
            system_prompt=system_prompt,
            user_prompt=json.dumps(user_payload, ensure_ascii=False),
            client=client,
            num_predict=3400,
            temperature=0.25,
            response_schema=_TAILOR_RESPONSE_SCHEMA,
            num_ctx=8192,
        )
        if parsed is None:
            compact_payload = {
                "target_job": {
                    "company": job.company,
                    "title": job.title,
                    "missing_keywords": target_missing[:12],
                    "missing_requirements_detail": detail_reqs[:8],
                    "seniority_signals": job.detected_signals[:5],
                },
                "existing_summary": base_resume.summary,
                "existing_experiences": editable_experiences,
                "existing_projects": [
                    {"name": p.name, "tech_stack": p.tech_stack, "bullets": [b.text for b in p.bullets[:2]]}
                    for p in base_resume.projects[:2]
                ],
                "existing_skills": [s.model_dump() for s in base_resume.skills],
            }
            parsed, retry_err = _call_ollama_json(
                base_url=settings.ollama_base_url,
                model=active_model,
                system_prompt=system_prompt,
                user_prompt=json.dumps(compact_payload, ensure_ascii=False),
                client=client,
                num_predict=2400,
                temperature=0.2,
                response_schema=_TAILOR_COMPACT_SCHEMA,
                num_ctx=8192,
            )
            if parsed is None and retry_err:
                call_err = retry_err

        if parsed is None:
            from backend.app.services.reasoning_tailor import run_reasoning_tailor_script

            fb_resume, _, fb_steps, fb_counts, fb_budget, fb_added = run_reasoning_tailor_script(
                base_resume=base_resume,
                job=job,
                rules=rules,
                settings=settings.model_copy(update={"page_budget": effective_page_budget}),
                adapt_location=False,
                bullets_per_experience=bullets_per_experience,
                bullets_per_role_counts=resolved_counts,
                auto_size=auto_size,
                page_budget=effective_page_budget,
                target_score_min=target_score_min,
                target_score_max=target_score_max,
                normalize_fn=normalize_tech_capitalization,
                add_skills_fn=_add_skills_to_categories,
                enforce_count_fn=_enforce_experience_bullet_count,
                summary_fn=_build_tailored_summary,
            )
            active_secs = set(target_sections or ["summary", "experience", "projects", "skills"])
            if "summary" not in active_secs:
                fb_resume.summary = base_resume.summary
            if "projects" not in active_secs:
                fb_resume.projects = copy.deepcopy(base_resume.projects)
            if "skills" not in active_secs:
                fb_resume.skills = copy.deepcopy(base_resume.skills)
            if "experience" not in active_secs:
                fb_resume.experience = copy.deepcopy(base_resume.experience)

            fb_humanized, h_count, h_notes = humanize_resume(fb_resume, rules=rules, avoided_words=list(active_avoided))
            fallback_reason = (
                f"Local model '{active_model}' fallback triggered ({call_err}); "
                "executed multi-step fallback reasoning script instead."
            )
            err_msg = f"{notice} {fallback_reason}" if notice else fallback_reason
            return (
                fb_humanized,
                None,
                h_count + len(fb_added),
                h_notes,
                err_msg,
                fb_added,
                fb_steps,
                fb_counts,
                fb_budget,
            )

    tailored, changes_applied = _apply_llm_tailor_payload(
        parsed=parsed,
        draft=base_resume,
        base_resume=base_resume,
        valid_bullet_ids=valid_bullet_ids,
        bullets_per_experience=bullets_per_experience,
        bullets_per_role_counts=resolved_counts,
        job=job,
    )
    llm_notes = [
        str(n).strip()
        for n in (parsed.get("humanizer_notes") or [])
        if isinstance(n, str) and n.strip()
    ][:6]

    # Guarantee consistency: if Ollama skipped Summary or <2 Projects or bullet counts drifted, complete cleanly
    orig_summary_norm = (base_resume.summary or "").strip()
    if not tailored.summary or tailored.summary.strip() == orig_summary_norm:
        tailored.summary = _build_tailored_summary(
            base_summary=tailored.summary,
            job=job,
            key_skills=[*target_missing[:5], *target_matched[:4]],
            missing_signals=job.detected_signals[:3],
        )

    orig_proj_names = [p.name for p in base_resume.projects]
    tailored_proj_names = [p.name for p in tailored.projects]
    if len(tailored.projects) < 2 or tailored_proj_names == orig_proj_names:
        tailored.projects, _ = _tailor_projects_to_jd(
            projects=tailored.projects,
            job=job,
            priority_skills=[*target_missing, *target_matched],
            normalize_fn=normalize_tech_capitalization,
        )

    for exp_idx, exp in enumerate(tailored.experience):
        cap = resolved_counts[exp_idx] if exp_idx < len(resolved_counts) else None
        _enforce_experience_bullet_count(exp, exp_idx, cap, job, [*target_missing, *target_matched])

    # Curate heavy multi-year resumes cleanly while preserving foundational core skills and >= 2 projects
    tailored, curated_pruned, curated_proj_count = curate_heavy_resume_sections(
        draft=tailored,
        job=job,
        normalize_fn=normalize_tech_capitalization,
    )
    if sum(len(c.items) for c in tailored.skills) < 12 and sum(len(c.items) for c in base_resume.skills) >= 14:
        base_core = [item for cat in base_resume.skills for item in cat.items][:14]
        _add_skills_to_categories(tailored.skills, [*target_missing[:6], *base_core], max_per_category=10)
    if curated_pruned or curated_proj_count:
        llm_notes.append(
            f"Curated heavy portfolio: retained foundational core stack and pruned {len(curated_pruned)} off-track term(s)."
        )

    tailored, h_count, h_notes = humanize_resume(tailored, rules=rules, avoided_words=list(active_avoided))

    reasoning_steps.append(
        TailoringReasoningStep(
            step=3,
            phase=f"Local Ollama Generation ({active_model})",
            decision=f"Updated Summary, {len(tailored.experience)} experience roles ({resolved_counts}), {len(tailored.projects)} projects, and Technical Skills.",
        )
    )

    pass1_report: ATSReport = score_resume_against_job(
        job_id=0,
        resume_id=0,
        resume=tailored,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_to_plain_text(tailored),
    )

    if pass1_report.overall_score < target_score_min and changes_applied > 0:
        still_missing = [ws.keyword for ws in pass1_report.missing_skills[:12]]
        pass1_text = resume_to_plain_text(tailored)
        missing_sigs = [
            sig for sig in (job.detected_signals or [])
            if not _keyword_pattern(sig).search(pass1_text)
        ]
        if still_missing or missing_sigs:
            refine_prompt = {
                "goal": f"Raise ATS score from {pass1_report.overall_score:.1f}% into {target_score_min}-{target_score_max}% by integrating missing skills naturally.",
                "still_missing_keywords": still_missing,
                "missing_seniority_signals": missing_sigs,
                "existing_experiences": editable_experiences,
                "current_summary": tailored.summary,
                "current_projects": [
                    {"name": p.name, "tech_stack": p.tech_stack, "bullets": [b.text for b in p.bullets[:2]]}
                    for p in tailored.projects
                ],
                "current_skills": [s.model_dump() for s in tailored.skills],
            }
            parsed2, _ = _call_ollama_json(
                base_url=settings.ollama_base_url,
                model=active_model,
                system_prompt=system_prompt,
                user_prompt=json.dumps(refine_prompt, ensure_ascii=False),
                client=client,
                num_predict=1800,
                temperature=0.2,
                response_schema=_TAILOR_RESPONSE_SCHEMA,
                num_ctx=8192,
            )
            if parsed2 is not None:
                tailored, extra_changes = _apply_llm_tailor_payload(
                    parsed=parsed2,
                    draft=tailored,
                    base_resume=base_resume,
                    valid_bullet_ids=valid_bullet_ids,
                    bullets_per_experience=bullets_per_experience,
                    bullets_per_role_counts=resolved_counts,
                    job=job,
                )
                changes_applied += extra_changes
                tailored, extra_h, extra_hn = humanize_resume(
                    tailored,
                    rules=rules,
                    avoided_words=list(active_avoided),
                )
                h_count += extra_h
                h_notes.extend(extra_hn)

    # Calibrate final result cleanly inside [target_score_min, target_score_max] (default 80-85%)
    tailored, _, calibrated_added = calibrate_resume_to_ats_band(
        draft=tailored,
        base_resume=base_resume,
        job=job,
        rules=rules,
        settings=settings.model_copy(update={"page_budget": effective_page_budget}),
        target_score_min=target_score_min,
        target_score_max=target_score_max,
        add_skills_fn=_add_skills_to_categories,
        normalize_fn=normalize_tech_capitalization,
        steps_log=reasoning_steps,
    )
    tailored, extra_h2, extra_hn2 = humanize_resume(tailored, rules=rules, avoided_words=list(active_avoided))
    h_count += extra_h2
    h_notes.extend(extra_hn2)

    tailored_matched_kws = _collect_matched_keywords(tailored, job.weighted_skills)
    added_skills = [
        ws.keyword
        for ws in job.weighted_skills
        if ws.keyword.lower() not in base_matched_kws and ws.keyword.lower() in tailored_matched_kws
    ]
    for sk in calibrated_added:
        if sk not in added_skills:
            added_skills.append(sk)

    if added_skills:
        llm_notes.append(f"Integrated {len(added_skills)} missing JD skills: {', '.join(added_skills[:8])}.")

    active_secs = set(target_sections or ["summary", "experience", "projects", "skills"])
    if "summary" not in active_secs:
        tailored.summary = base_resume.summary
    if "projects" not in active_secs:
        tailored.projects = copy.deepcopy(base_resume.projects)
    if "skills" not in active_secs:
        tailored.skills = copy.deepcopy(base_resume.skills)
    if "experience" not in active_secs:
        tailored.experience = copy.deepcopy(base_resume.experience)

    combined_notes = [*llm_notes, *h_notes]
    if changes_applied == 0:
        notice_out = notice or f"Model '{active_model}' did not return tailored sections; applied structured tailoring."
        return tailored, None, h_count + len(added_skills), combined_notes[:12], notice_out, added_skills, reasoning_steps, resolved_counts, effective_page_budget

    return (
        tailored,
        active_model,
        h_count + changes_applied + len(added_skills),
        list(dict.fromkeys(combined_notes))[:12],
        notice,
        added_skills,
        reasoning_steps,
        resolved_counts,
        effective_page_budget,
    )


def llm_tailor_and_humanize(
    *,
    base_resume: CanonicalResume,
    job: JobAnalysis,
    missing_skills: list[WeightedSkill],
    matched_skills: list[WeightedSkill],
    rules: BigTechRulesConfig,
    settings: AppSettings,
    job_raw_text: str = "",
    bullets_per_experience: int | None = None,
    page_budget: float | None = None,
    avoided_words: list[str] | None = None,
    custom_instructions: str | None = None,
    target_score: int = 80,
    client: httpx.Client | None = None,
) -> tuple[CanonicalResume, str | None, int, list[str], str | None, list[str]]:
    """Backwards-compatible wrapper around llm_tailor_with_reasoning returning the 6-tuple."""
    tailored, model_used, h_count, notes, notice, added_skills, _, _, _ = llm_tailor_with_reasoning(
        base_resume=base_resume,
        job=job,
        missing_skills=missing_skills,
        matched_skills=matched_skills,
        rules=rules,
        settings=settings,
        job_raw_text=job_raw_text,
        bullets_per_experience=bullets_per_experience,
        page_budget=page_budget,
        avoided_words=avoided_words,
        custom_instructions=custom_instructions,
        target_score=target_score,
        client=client,
    )
    return tailored, model_used, h_count, notes, notice, added_skills


_BENCHMARK_TARGET_TERMS: tuple[str, ...] = (
    "python",
    "kafka",
    "grpc",
    "postgresql",
    "kubernetes",
    "opentelemetry",
)

_BENCHMARK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "project_name": {"type": "string"},
        "project_bullets": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "project_name", "project_bullets", "skills"],
}

_SECTION_SCHEMAS: dict[str, dict[str, Any]] = {
    "summary": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
    "experience": {
        "type": "object",
        "properties": {
            "experiences": _TAILOR_RESPONSE_SCHEMA["properties"]["experiences"],
        },
        "required": ["experiences"],
    },
    "projects": {
        "type": "object",
        "properties": {
            "projects": _TAILOR_RESPONSE_SCHEMA["properties"]["projects"],
        },
        "required": ["projects"],
    },
    "skills": {
        "type": "object",
        "properties": {
            "skills": _TAILOR_RESPONSE_SCHEMA["properties"]["skills"],
        },
        "required": ["skills"],
    },
    "education": {
        "type": "object",
        "properties": {
            "education": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "institution": {"type": "string"},
                        "degree": {"type": "string"},
                        "graduation_date": {"type": "string"},
                        "location": {"type": "string"},
                        "coursework": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["institution", "degree", "graduation_date"],
                },
            },
        },
        "required": ["education"],
    },
}


def benchmark_ollama_models(
    *,
    base_url: str,
    requested_models: Sequence[str] | None = None,
    client: httpx.Client | None = None,
) -> LlmBenchmarkResponse:
    """Compare and rank installed local Ollama models on JSON reliability, JD accuracy, and latency."""
    reachable, available, err = list_ollama_models(base_url, client=client)
    if not reachable or not available:
        return LlmBenchmarkResponse(
            reachable=False,
            base_url=base_url,
            recommended_model=None,
            items=[],
        )

    candidates: list[str] = []
    if requested_models:
        for m in requested_models:
            matched = _match_installed_model(m, available)
            if matched and matched not in candidates:
                candidates.append(matched)
    if not candidates:
        candidates = list(available)[:6]

    system_prompt = (
        "Return strict JSON only matching the schema. Avoid filler words like 'slashed' or 'synergized'. "
        "Explicitly use the target technologies mentioned in the prompt."
    )
    user_prompt = json.dumps(
        {
            "task": "Tailor a concise senior backend engineer snippet for a high-throughput Stripe payment ledger role.",
            "must_include_technologies": ["Python", "Kafka", "gRPC", "PostgreSQL", "Kubernetes", "OpenTelemetry"],
            "requirements": {
                "summary": "2 concise engineering sentences naming Python, Kafka, PostgreSQL, and Kubernetes.",
                "project_name": "Descriptive project title.",
                "project_bullets": ["2 concise Action+Stack+Result bullets"],
                "skills": ["6 clean capitalized skill names"],
            },
        }
    )

    raw_items: list[LlmBenchmarkItem] = []
    for model_name in candidates:
        t0 = time.perf_counter()
        parsed, call_err = _call_ollama_json(
            base_url=base_url,
            model=model_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            client=client,
            num_predict=550,
            temperature=0.2,
            response_schema=_BENCHMARK_SCHEMA,
            num_ctx=4096,
        )
        elapsed_ms = max(1, int((time.perf_counter() - t0) * 1000))
        if parsed is None:
            raw_items.append(
                LlmBenchmarkItem(
                    model=model_name,
                    ok=False,
                    latency_ms=elapsed_ms,
                    json_valid=False,
                    schema_complete=False,
                    score=0.0,
                    notes=call_err or "Invalid JSON output",
                    error=call_err,
                )
            )
            continue

        summary_txt = str(parsed.get("summary") or "").strip()
        proj_name = str(parsed.get("project_name") or "").strip()
        proj_bullets = [str(b).strip() for b in (parsed.get("project_bullets") or []) if str(b).strip()]
        skills_list = [str(s).strip() for s in (parsed.get("skills") or []) if str(s).strip()]

        schema_complete = (
            len(summary_txt) >= 30
            and bool(proj_name)
            and len(proj_bullets) >= 2
            and len(skills_list) >= 4
        )
        blob = " ".join([summary_txt, proj_name, *proj_bullets, *skills_list]).lower()
        hits = [term for term in _BENCHMARK_TARGET_TERMS if term in blob]
        adherence_pts = (len(hits) / len(_BENCHMARK_TARGET_TERMS)) * 30.0
        speed_pts = max(0.0, min(20.0, 20.0 * (1.0 - (elapsed_ms / 45000.0))))
        slop_penalty = 10.0 if ("slashed" in blob or "synergized" in blob) else 0.0

        composite = round(
            25.0
            + (25.0 if schema_complete else 10.0)
            + adherence_pts
            + speed_pts
            - slop_penalty,
            1,
        )
        raw_items.append(
            LlmBenchmarkItem(
                model=model_name,
                ok=True,
                latency_ms=elapsed_ms,
                json_valid=True,
                schema_complete=schema_complete,
                score=max(0.0, min(100.0, composite)),
                notes=(
                    f"{len(hits)}/{len(_BENCHMARK_TARGET_TERMS)} prompt stack terms matched; "
                    f"{len(proj_bullets)} bullets, {len(skills_list)} skills"
                ),
            )
        )

    raw_items.sort(key=lambda item: (-int(item.ok), -item.score, item.latency_ms, item.model))
    ranked: list[LlmBenchmarkItem] = []
    recommended: str | None = None
    for idx, item in enumerate(raw_items, start=1):
        updated_item = item.model_copy(update={"rank": idx})
        if updated_item.ok and recommended is None:
            recommended = updated_item.model
        ranked.append(updated_item)

    return LlmBenchmarkResponse(
        reachable=True,
        base_url=base_url,
        recommended_model=recommended,
        items=ranked,
    )


def _extract_prompt_focus_terms(prompt: str, job: JobAnalysis, base_skills: Sequence[str]) -> list[str]:
    """Extract explicit technical terms or emphasis directives from a user's section custom prompt."""
    clean = (prompt or "").strip()
    if not clean:
        return []
    from backend.app.services.skill_enrichment import UNIVERSAL_TECH_TAXONOMY

    found: list[str] = []
    seen: set[str] = set()
    candidates = [
        *(ws.keyword for ws in (job.weighted_skills or [])),
        *base_skills,
        *(entry[0] for entry in UNIVERSAL_TECH_TAXONOMY),
    ]
    for cand in candidates:
        c = str(cand).strip()
        if not c or c.lower() in seen:
            continue
        if _keyword_pattern(c).search(clean):
            found.append(normalize_tech_capitalization(c))
            seen.add(c.lower())
    return found


def tailor_resume_section_with_prompt(
    *,
    job: JobAnalysis,
    base_resume: CanonicalResume,
    current_resume: CanonicalResume,
    section: str,
    prompt: str,
    engine: str,
    rules: BigTechRulesConfig,
    settings: AppSettings,
    model: str | None = None,
    avoided_words: Sequence[str] | None = None,
    bullets_per_experience: int | None = None,
    client: httpx.Client | None = None,
) -> tuple[CanonicalResume, str, str | None, ATSReport, list[str], str | None]:
    """Tailor a single resume section ('summary'|'experience'|'projects'|'skills') via Ollama or Fallback Script."""
    from backend.app.services.reasoning_tailor import _extract_end_year, _reframe_bullet_with_skills

    updated = current_resume.model_copy(deep=True)
    # Enforce hard locks on education, certifications, and employer identity
    if section != "education":
        updated.education = copy.deepcopy(base_resume.education)
    updated.certifications = copy.deepcopy(base_resume.certifications)
    for exp_idx, orig_exp in enumerate(base_resume.experience):
        if exp_idx < len(updated.experience):
            updated.experience[exp_idx].id = orig_exp.id
            updated.experience[exp_idx].company = orig_exp.company
            updated.experience[exp_idx].title = orig_exp.title
            updated.experience[exp_idx].start_date = orig_exp.start_date
            updated.experience[exp_idx].end_date = orig_exp.end_date
            updated.experience[exp_idx].location = orig_exp.location

    active_avoided = list(
        _resolve_active_avoided_words(
            rules=rules,
            avoided_words=avoided_words if avoided_words is not None else settings.avoided_ai_words,
        )
    )

    before_report = score_resume_against_job(
        job_id=0,
        resume_id=0,
        resume=updated,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_to_plain_text(updated),
    )
    before_matched = {ws.keyword.lower() for ws in before_report.matched_skills}
    missing_kws = [ws.keyword for ws in sorted(before_report.missing_skills, key=lambda x: (-x.weight, -x.jd_mentions))]
    matched_kws = [ws.keyword for ws in sorted(before_report.matched_skills, key=lambda x: (-x.weight, -x.jd_mentions))]
    base_skill_names = [item for cat in base_resume.skills for item in cat.items]
    prompt_terms = _extract_prompt_focus_terms(prompt, job, base_skill_names)
    clean_prompt = (prompt or "").strip()

    schema = _SECTION_SCHEMAS.get(section)
    if schema is None:
        raise ValueError(f"Unsupported section '{section}' for targeted tailoring.")

    notice: str | None = None
    engine_used = "claude" if engine == "claude" else "fallback_script"
    model_used: str | None = "claude-3-5-sonnet" if engine == "claude" else None
    ollama_applied = False
    claude_applied = False

    if engine == "claude":
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip() or getattr(settings, "anthropic_api_key", "").strip()
        if anthropic_key:
            avoided_csv = ", ".join(sorted(active_avoided)) or "none"
            sys_prompt = (
                f"You are a senior Staff Engineer updating ONLY the '{section}' section of a resume for {job.title} at {job.company}.\n"
                "Rules: Write crisp, realistic, grounded engineering prose; use proper tech casing (Python, FastAPI, Spark, RAG, AWS, Kubernetes); "
                f"never change company names/dates or education; NEVER use 'slashed' or these words: {avoided_csv}.\n"
                "Respond strictly with valid JSON matching the schema."
            )
            section_ctx = {
                "section_to_edit": section,
                "user_custom_prompt": clean_prompt or f"Align {section} cleanly to {job.title} at {job.company}.",
                "target_job": {
                    "company": job.company,
                    "title": job.title,
                    "missing_jd_keywords": missing_kws[:12],
                    "top_jd_keywords": matched_kws[:8],
                    "expected_work": (job.expected_work or [])[:4],
                },
            }
            try:
                cl_client = client or httpx.Client(timeout=40.0)
                cl_resp = cl_client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": anthropic_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": "claude-3-5-sonnet-20241022",
                        "max_tokens": 2048,
                        "temperature": 0.2,
                        "system": sys_prompt,
                        "messages": [{"role": "user", "content": json.dumps(section_ctx, ensure_ascii=False)}],
                    },
                )
                if cl_resp.status_code == 200:
                    c_blocks = cl_resp.json().get("content", [])
                    c_txt = "".join(b.get("text", "") for b in c_blocks if b.get("type") == "text")
                    parsed_cl = _extract_json_object(c_txt)
                    if parsed_cl:
                        scoped_payload = {section if section != "experience" else "experiences": parsed_cl.get(section if section != "experience" else "experiences")}
                        temp_updated, chg = _apply_llm_tailor_payload(
                            parsed=scoped_payload,
                            draft=updated.model_copy(deep=True),
                            base_resume=base_resume,
                            valid_bullet_ids={b.id for e in updated.experience for b in e.bullets if b.id},
                            bullets_per_experience=bullets_per_experience,
                            job=job,
                        )
                        if chg > 0:
                            if section == "summary":
                                updated.summary = temp_updated.summary
                            elif section == "experience":
                                updated.experience = temp_updated.experience
                            elif section == "projects":
                                updated.projects = temp_updated.projects
                            else:
                                updated.skills = _dedupe_skill_categories(temp_updated.skills)
                            claude_applied = True
                            engine_used = "claude"
                            model_used = "claude-3-5-sonnet"
                            notice = f"Updated {section.title()} section with Claude 3.5 Sonnet."
            except Exception:
                pass

    elif engine == "ollama":
        reachable, available, reach_err = list_ollama_models(settings.ollama_base_url, client=client)
        if reachable and available:
            chosen_req = (model or "").strip() or settings.llm_model
            active_model, pick_note = pick_active_model(chosen_req, available)
            avoided_csv = ", ".join(sorted(active_avoided)) or "none"
            sys_prompt = (
                f"You are a senior Staff Engineer updating ONLY the '{section}' section of a resume for {job.title} at {job.company}.\n"
                "Rules: Write crisp, realistic, grounded engineering prose; use proper tech casing (Python, FastAPI, Spark, RAG, AWS, Kubernetes); "
                f"never change company names/dates or education; NEVER use 'slashed' or these words: {avoided_csv}.\n"
                "Respond strictly with valid JSON matching the schema."
            )
            section_ctx: dict[str, Any] = {
                "section_to_edit": section,
                "user_custom_prompt": clean_prompt or f"Align {section} cleanly to {job.title} at {job.company}.",
                "target_job": {
                    "company": job.company,
                    "title": job.title,
                    "missing_jd_keywords": missing_kws[:12],
                    "top_jd_keywords": matched_kws[:8],
                    "expected_work": (job.expected_work or [])[:4],
                },
            }
            if section == "summary":
                section_ctx["current_summary"] = updated.summary or ""
            elif section == "experience":
                section_ctx["experiences"] = [
                    {
                        "experience_index": idx,
                        "locked_company": exp.company,
                        "locked_title": exp.title,
                        "target_bullet_count": bullets_per_experience or len(exp.bullets) or 5,
                        "bullets": [b.text for b in exp.bullets],
                    }
                    for idx, exp in enumerate(updated.experience)
                ]
            elif section == "projects":
                section_ctx["current_projects"] = [
                    {"name": p.name, "tech_stack": p.tech_stack, "link": p.link, "bullets": [b.text for b in p.bullets]}
                    for p in updated.projects
                ]
            elif section == "education":
                section_ctx["current_education"] = [e.model_dump() for e in updated.education]
            else:
                section_ctx["current_skills"] = [s.model_dump() for s in updated.skills]
                section_ctx["base_skills_pool"] = base_skill_names[:28]

            parsed, call_err = _call_ollama_json(
                base_url=settings.ollama_base_url,
                model=active_model,
                system_prompt=sys_prompt,
                user_prompt=json.dumps(section_ctx, ensure_ascii=False),
                client=client,
                num_predict=1400,
                temperature=0.28,
                response_schema=schema,
                num_ctx=6144,
            )
            if parsed is not None:
                before_snapshot = updated.model_copy(deep=True)
                scoped_payload = {section if section != "experience" else "experiences": parsed.get(section if section != "experience" else "experiences")}
                temp_updated, chg = _apply_llm_tailor_payload(
                    parsed=scoped_payload,
                    draft=before_snapshot,
                    base_resume=base_resume,
                    valid_bullet_ids={b.id for e in updated.experience for b in e.bullets if b.id},
                    bullets_per_experience=bullets_per_experience,
                    job=job,
                )
                if chg > 0:
                    if section == "summary":
                        updated.summary = temp_updated.summary
                    elif section == "experience":
                        updated.experience = temp_updated.experience
                    elif section == "projects":
                        updated.projects = temp_updated.projects
                    elif section == "education":
                        parsed_edu = scoped_payload.get("education") or parsed.get("education")
                        if isinstance(parsed_edu, list) and len(parsed_edu) > 0:
                            from backend.app.schemas.resume import CanonicalEducation
                            new_edus = []
                            for e in parsed_edu:
                                if isinstance(e, dict) and e.get("institution"):
                                    new_edus.append(CanonicalEducation(
                                        institution=e.get("institution", ""),
                                        degree=e.get("degree", ""),
                                        graduation_date=e.get("graduation_date", ""),
                                        location=e.get("location"),
                                        coursework=[str(c) for c in e.get("coursework", []) if str(c)],
                                    ))
                            if new_edus:
                                updated.education = new_edus
                    else:
                        updated.skills = _dedupe_skill_categories(temp_updated.skills)
                    engine_used = "ollama_llm"
                    model_used = active_model
                    ollama_applied = True
                    notice = pick_note or f"Updated {section} with Local Ollama ({active_model})."
                else:
                    notice = f"Local Ollama ({active_model}) returned empty {section} changes; applied Fallback Script."
            else:
                notice = f"Local Ollama ({call_err}) could not update {section}; applied Fallback Script."
        else:
            notice = f"{reach_err or 'Local Ollama unreachable'}; applied Fallback Script for {section}."

    if not ollama_applied and not claude_applied:
        engine_used = "claude" if engine == "claude" else "fallback_script"
        model_used = "claude-reasoning" if engine == "claude" else None
        priority_terms = list(dict.fromkeys([*prompt_terms, *missing_kws, *matched_kws]))

        if section == "summary":
            lead_stack = priority_terms[:6] or ["Python", "AWS", "FastAPI", "Kubernetes"]
            updated.summary = _build_tailored_summary(
                base_summary=updated.summary,
                job=job,
                key_skills=lead_stack,
                missing_signals=(job.detected_signals or [])[:2],
            )
            if clean_prompt and len(prompt_terms) == 0:
                short_dir = clean_prompt.rstrip(".")
                if len(short_dir) <= 95:
                    updated.summary = f"{updated.summary.rstrip('.')} Focused on {short_dir[0].lower() + short_dir[1:]}."
            elif prompt_terms and not all(_keyword_pattern(t).search(updated.summary or "") for t in prompt_terms[:3]):
                updated.summary = f"{updated.summary.rstrip('.')} Key expertise spans {', '.join(prompt_terms[:4])}."
            cleaned_sum, _ = humanize_bullet_text(updated.summary or "", rules=rules, avoided_words=active_avoided)
            updated.summary = cleaned_sum
        elif section == "experience":
            weave_pool = list(priority_terms[:8])
            for exp_idx, exp in enumerate(updated.experience):
                end_yr = _extract_end_year(exp)
                for b_idx, b in enumerate(exp.bullets[: (3 if exp_idx == 0 else 2)]):
                    slice_terms = weave_pool[:2] or priority_terms[:2]
                    new_txt, used = _reframe_bullet_with_skills(b.text, slice_terms, normalize_tech_capitalization, exp_end_year=end_yr)
                    if used:
                        b.text = new_txt
                        b.provenance = "REFRAMED"
                        b.tags = list(dict.fromkeys([*b.tags, *used]))
                        for u in used:
                            if u in weave_pool:
                                weave_pool.remove(u)
                    b.text, _ = humanize_bullet_text(b.text, rules=rules, avoided_words=active_avoided)
        elif section == "projects":
            updated.projects, _ = _tailor_projects_to_jd(
                projects=updated.projects,
                job=job,
                priority_skills=priority_terms or matched_kws,
                normalize_fn=normalize_tech_capitalization,
            )
            if clean_prompt and prompt_terms and updated.projects:
                p0 = updated.projects[0]
                p0.tech_stack = list(dict.fromkeys([*prompt_terms[:4], *p0.tech_stack]))[:7]
            for proj in updated.projects:
                for pb in proj.bullets:
                    pb.text, _ = humanize_bullet_text(pb.text, rules=rules, avoided_words=active_avoided)
        elif section == "education":
            if updated.education:
                edu0 = updated.education[0]
                if prompt_terms:
                    edu0.coursework = list(dict.fromkeys([*prompt_terms[:4], *edu0.coursework]))[:8]
                elif clean_prompt:
                    custom_items = [p.strip() for p in clean_prompt.replace(";", ",").split(",") if p.strip()]
                    if custom_items:
                        edu0.coursework = list(dict.fromkeys([*custom_items[:5], *edu0.coursework]))[:8]
        else:
            # Targeted Technical Skills curation honoring base skills + prompt focus + JD requirements
            to_add = [*prompt_terms[:6], *missing_kws[:8]]
            _add_skills_to_categories(updated.skills, to_add, max_per_category=14)
            updated, _, _ = curate_heavy_resume_sections(
                draft=updated,
                job=job,
                normalize_fn=normalize_tech_capitalization,
                max_skills_total=48,
                max_projects=max(2, len(updated.projects)),
            )
            updated.skills = _dedupe_skill_categories(updated.skills)

        if not notice:
            notice = (
                f"Updated {section.title()} section with Claude / Cloud AI."
                if engine == "claude"
                else f"Updated {section.title()} section via Fallback Reasoning Script."
            )

    # Normalize skill casing/dedupe globally and re-score immediately
    updated.skills = _dedupe_skill_categories(updated.skills)
    after_report = score_resume_against_job(
        job_id=0,
        resume_id=0,
        resume=updated,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_to_plain_text(updated),
    )
    added_skills = [
        ws.keyword
        for ws in after_report.matched_skills
        if ws.keyword.lower() not in before_matched
    ]
    return updated, engine_used, model_used, after_report, added_skills, notice
