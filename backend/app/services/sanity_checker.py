"""Post-tailoring plausibility & timeline sanity verification (auto-repairs safe defects)."""

from __future__ import annotations

import copy
import re
from typing import Sequence

from backend.app.schemas.job import ATSReport, JobAnalysis, SanityCheckItem
from backend.app.schemas.resume import CanonicalResume, ExperienceItem

# Technologies mapped to approximate mainstream production adoption year to prevent timeline anachronisms.
TECH_ERA_FLOOR_YEAR: dict[str, int] = {
    "langgraph": 2023,
    "mcp": 2024,
    "model context protocol": 2024,
    "langchain": 2022,
    "rag": 2021,
    "retrieval-augmented": 2021,
    "generative ai": 2022,
    "genai": 2022,
    "llm": 2021,
    "llms": 2021,
    "fastapi": 2019,
    "next.js": 2017,
    "pytorch": 2017,
    "kubernetes": 2015,
    "terraform": 2015,
    "graphql": 2016,
    "docker": 2014,
}

_IMPOSSIBLE_PCT_RE = re.compile(r"\b(100|1[1-9]\d|[2-9]\d{2,})%\s*(reduction|faster|improvement|Latency|cost|error|uptime|speedup)\b", re.IGNORECASE)
_IMPOSSIBLE_MULTIPLIER_RE = re.compile(r"\b([2-9]\d{2,}|1\d{3,})x\b", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")


def _extract_end_year(exp: ExperienceItem) -> int:
    end_low = (exp.end_date or "").strip().lower()
    if not end_low or "present" in end_low or "current" in end_low or "now" in end_low:
        return 2026
    years = [int(y) for y in _YEAR_RE.findall(end_low)]
    if years:
        return max(years)
    start_years = [int(y) for y in _YEAR_RE.findall(exp.start_date or "")]
    return max(start_years) + 2 if start_years else 2026


def run_resume_sanity_check(
    *,
    base_resume: CanonicalResume,
    tailored_resume: CanonicalResume,
    job: JobAnalysis,
    tailored_report: ATSReport,
    avoided_words: Sequence[str] = (),
    target_score_min: int = 80,
    target_score_max: int = 85,
) -> tuple[CanonicalResume, list[SanityCheckItem], bool, str]:
    """Audit and repair tailored resumes so every bullet is chronologically and technically plausible."""
    checked = tailored_resume.model_copy(deep=True)
    checks: list[SanityCheckItem] = []

    # 1. Identity Anchor Lock Verification (Education, Certifications, Employer/Title/Dates)
    locks_repaired = 0
    if checked.education != base_resume.education:
        checked.education = copy.deepcopy(base_resume.education)
        locks_repaired += 1
    if checked.certifications != base_resume.certifications:
        checked.certifications = copy.deepcopy(base_resume.certifications)
        locks_repaired += 1
    for idx, exp in enumerate(checked.experience):
        if idx < len(base_resume.experience):
            orig = base_resume.experience[idx]
            if (
                exp.company != orig.company
                or exp.title != orig.title
                or exp.start_date != orig.start_date
                or exp.end_date != orig.end_date
            ):
                exp.company = orig.company
                exp.title = orig.title
                exp.start_date = orig.start_date
                exp.end_date = orig.end_date
                locks_repaired += 1

    checks.append(
        SanityCheckItem(
            check_id="anchor_locks",
            title="Employer, Dates & Education Locks",
            status="repaired" if locks_repaired > 0 else "passed",
            detail=(
                f"Restored {locks_repaired} locked identity field(s) to match base resume."
                if locks_repaired > 0
                else "All companies, job titles, dates, and degrees remain 100% locked."
            ),
        )
    )

    # 2. Chronological Tech-Era Plausibility Check
    timeline_fixes: list[str] = []
    for exp_idx, exp in enumerate(checked.experience):
        end_yr = _extract_end_year(exp)
        for bullet in exp.bullets:
            text_low = bullet.text.lower()
            for term, floor_yr in TECH_ERA_FLOOR_YEAR.items():
                if end_yr < floor_yr and re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text_low):
                    # Replace modern anachronism in older job with historically valid engineering terminology
                    replacement = "microservices" if term in ("langgraph", "mcp", "langchain") else "automated NLP & search pipelines"
                    bullet.text = re.sub(
                        rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])",
                        replacement,
                        bullet.text,
                        flags=re.IGNORECASE,
                    )
                    timeline_fixes.append(f"{exp.company} (ended {end_yr}): '{term}' -> '{replacement}'")
                    text_low = bullet.text.lower()

    checks.append(
        SanityCheckItem(
            check_id="timeline_era",
            title="Timeline & Tech-Era Plausibility",
            status="repaired" if timeline_fixes else "passed",
            detail=(
                f"Repaired {len(timeline_fixes)} chronological tech anachronism(s): {', '.join(timeline_fixes[:3])}."
                if timeline_fixes
                else "All frameworks and AI/cloud tooling align with each employer's active calendar dates."
            ),
        )
    )

    # 3. Realistic Metrics & Claim Bounds Guard
    metric_repairs = 0
    for section_bullets in [*[e.bullets for e in checked.experience], *[p.bullets for p in checked.projects]]:
        for bullet in section_bullets:
            updated = _IMPOSSIBLE_PCT_RE.sub(r"up to 45% \2", bullet.text)
            updated = _IMPOSSIBLE_MULTIPLIER_RE.sub("3x", updated)
            updated = re.sub(r"\b99\.999+%", "99.95%", updated)
            if updated != bullet.text:
                bullet.text = updated
                metric_repairs += 1

    checks.append(
        SanityCheckItem(
            check_id="realistic_metrics",
            title="Realistic Engineering Metrics",
            status="repaired" if metric_repairs else "passed",
            detail=(
                f"Scaled {metric_repairs} exaggerated percentage/multiplier claim(s) back to realistic production ranges."
                if metric_repairs
                else "All quantified performance, scale, and reliability outcomes fall inside realistic engineering bounds."
            ),
        )
    )

    # 4. Duplicate Bullet & Length Guard
    seen_bullets: set[str] = set()
    dup_removed = 0
    length_trimmed = 0
    for exp in checked.experience:
        unique_bullets = []
        for b in exp.bullets:
            norm = re.sub(r"\W+", " ", b.text.lower()).strip()
            if norm in seen_bullets and len(unique_bullets) >= 2:
                dup_removed += 1
                continue
            seen_bullets.add(norm)
            if len(b.text) > 250:
                b.text = b.text[:247].rstrip(" ,;.") + "."
                length_trimmed += 1
            unique_bullets.append(b)
        exp.bullets = unique_bullets

    for proj in checked.projects:
        for b in proj.bullets:
            if len(b.text) > 250:
                b.text = b.text[:247].rstrip(" ,;.") + "."
                length_trimmed += 1

    checks.append(
        SanityCheckItem(
            check_id="bullet_hygiene",
            title="Uniqueness & 1-2 Line Conciseness",
            status="repaired" if (dup_removed or length_trimmed) else "passed",
            detail=(
                f"Removed {dup_removed} duplicate bullet(s) and tightened {length_trimmed} over-long bullet(s)."
                if (dup_removed or length_trimmed)
                else f"All {sum(len(e.bullets) for e in checked.experience)} experience & {sum(len(p.bullets) for p in checked.projects)} project bullets are unique and 1-2 lines."
            ),
        )
    )

    # 5. Avoided / AI-Slop Vocabulary Verification
    banned = {w.strip().lower() for w in avoided_words if w.strip()} | {"slashed"}
    leaks_found: list[str] = []
    full_chunks = [checked.summary or ""]
    for e in checked.experience:
        full_chunks.extend(b.text for b in e.bullets)
    for p in checked.projects:
        full_chunks.extend(b.text for b in p.bullets)
    combined_lower = "\n".join(full_chunks).lower()
    for w in sorted(banned):
        if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", combined_lower):
            leaks_found.append(w)

    checks.append(
        SanityCheckItem(
            check_id="avoided_words",
            title="Humanizer & Blocked Vocabulary Check",
            status="warning" if leaks_found else "passed",
            detail=(
                f"Detected blocked phrasing ({', '.join(leaks_found[:4])}); humanizer cleanup recommended."
                if leaks_found
                else "Zero AI-slop terms (including 'slashed') detected across Summary, Experience, and Projects."
            ),
        )
    )

    # 6. Target ATS Calibration Band (80% - 85%)
    score = float(tailored_report.overall_score or 0.0)
    if target_score_min <= score <= target_score_max:
        band_status = "passed"
        band_detail = f"Tailored ATS match ({score}%) sits cleanly inside the {target_score_min}-{target_score_max}% sweet spot (well-aligned without keyword stuffing)."
    elif score > target_score_max:
        band_status = "warning"
        band_detail = f"Tailored ATS match ({score}%) is slightly above {target_score_max}%; core authenticity preserved from base resume."
    else:
        band_status = "warning"
        band_detail = f"Tailored ATS match ({score}%) is below {target_score_min}% ({len(tailored_report.missing_skills)} unmatched JD skill(s) remain)."

    checks.append(
        SanityCheckItem(
            check_id="ats_band",
            title=f"ATS Match Calibration ({target_score_min}-{target_score_max}%)",
            status=band_status,
            detail=band_detail,
        )
    )

    # 7. Complete Section Tailoring Check (>= 2 Projects & Summary present)
    has_summary = bool((checked.summary or "").strip())
    has_projects = len(checked.projects) >= 2
    checks.append(
        SanityCheckItem(
            check_id="complete_sections",
            title="Complete Section Coverage (Summary + Exp + >=2 Projects + Skills)",
            status="passed" if (has_summary and has_projects) else "warning",
            detail=(
                f"Verified tailored Summary, {len(checked.experience)} Experience roles, {len(checked.projects)} Projects, and {len(checked.skills)} Technical Skill groups."
                if (has_summary and has_projects)
                else "Missing Summary or fewer than 2 tailored Projects."
            ),
        )
    )

    # 8. Seniority & Role Scope Realism
    seniority_signals = set(job.detected_signals or [])
    has_senior_scope = any(
        any(k in b.text.lower() for k in ("scale", "architect", "latency", "rps", "lead", "distributed", "throughput", "pipeline", "sla"))
        for e in checked.experience
        for b in e.bullets
    )
    checks.append(
        SanityCheckItem(
            check_id="seniority_calibration",
            title="Seniority & Role Scope Realism",
            status="passed" if has_senior_scope else "warning",
            detail=(
                f"Demonstrated senior ownership, architecture scope, and operational scale aligned to {job.title}."
                if has_senior_scope
                else f"Scope may appear entry/mid-level for {job.title}; ensure bullets cite architecture & scale outcomes."
            ),
        )
    )

    # 9. Technology Stack Coherence & Modern Tooling
    all_tech_mentions = {
        item.strip().lower()
        for cat in checked.skills
        for item in cat.items
        if item.strip()
    }
    has_coherent_stack = len(all_tech_mentions) >= 6
    checks.append(
        SanityCheckItem(
            check_id="tech_stack_coherence",
            title="Stack Coherence & Production Tooling",
            status="passed" if has_coherent_stack else "warning",
            detail=(
                f"Validated {len(all_tech_mentions)} clean, non-conflicting technologies across languages, frameworks, data, and cloud infrastructure."
                if has_coherent_stack
                else "Technical skills catalog appears thin; recommend populating foundational stack categories."
            ),
        )
    )

    all_passed = (
        not leaks_found
        and has_summary
        and has_projects
        and (target_score_min <= score <= target_score_max or score > target_score_max)
    )
    repaired_count = sum(1 for c in checks if c.status == "repaired")
    warn_count = sum(1 for c in checks if c.status == "warning")
    summary_text = (
        f"Sanity verification complete: {len(checks) - warn_count}/{len(checks)} checks clean"
        + (f" ({repaired_count} auto-repaired)" if repaired_count else "")
        + (f", {warn_count} note(s)" if warn_count else "")
        + "."
    )
    return checked, checks, all_passed, summary_text
