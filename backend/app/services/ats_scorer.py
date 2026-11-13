"""Deterministic Big Tech Senior ATS scoring engine and ranked gap analyzer."""

from __future__ import annotations

import math
import re

from backend.app.schemas.config import AppSettings, BigTechRulesConfig
from backend.app.schemas.job import ATSReport, BulletDiagnostic, JobAnalysis, WeightedSkill
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.jd_analyzer import SENIOR_SIGNALS, _keyword_pattern
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.skill_enrichment import (
    build_missing_requirements,
    enrich_job_weighted_skills,
    extract_all_resume_skills,
)

METRIC_RE = re.compile(
    r"(?:\d+(?:\.\d+)?\s*(?:%|x|ms|s|sec|mins?|hrs?|k|m|b|tb|gb|mb|qps|rps|tps)\b|\$\s*\d+)",
    re.IGNORECASE,
)


def _evaluate_bullet(
    section: str,
    parent_name: str,
    text: str,
    strong_verbs: set[str],
    weak_phrases: list[str],
    ai_slop_words: list[str],
    max_chars: int,
) -> BulletDiagnostic:
    clean = text.strip()
    lower = clean.lower()
    hyphen_match = re.match(r"^[a-z]+(?:-[a-z]+)?", lower)
    first_word = hyphen_match.group(0) if hyphen_match else (re.split(r"[^a-z]+", lower)[0] if lower else "")

    has_strong_verb = first_word in strong_verbs
    has_metric = bool(METRIC_RE.search(clean) or re.search(r"\b\d{2,}\b", clean))
    weak_found = [phrase for phrase in weak_phrases if phrase in lower]
    slop_found = [word for word in ai_slop_words if _keyword_pattern(word).search(clean)]

    return BulletDiagnostic(
        section=section,
        parent_name=parent_name,
        bullet_text=clean,
        has_strong_verb=has_strong_verb,
        has_quantified_metric=has_metric,
        weak_phrases_found=weak_found,
        ai_slop_found=slop_found,
        exceeds_max_length=len(clean) > max_chars,
    )


def score_resume_against_job(
    job_id: int,
    resume_id: int,
    resume: CanonicalResume,
    job: JobAnalysis,
    rules: BigTechRulesConfig,
    settings: AppSettings,
    raw_resume_text: str = "",
    raw_job_text: str | None = None,
) -> ATSReport:
    """Compute explainable ATS match score (0-100), full resume skills, and ranked missing gaps."""
    canonical_text = resume_to_plain_text(resume).strip()
    searchable_text = canonical_text if canonical_text else (raw_resume_text or "").strip()

    effective_job = job
    if raw_job_text and raw_job_text.strip():
        enriched_skills = enrich_job_weighted_skills(raw_job_text, job.weighted_skills)
        effective_job = job.model_copy(update={"weighted_skills": enriched_skills})

    # 1. Weighted keyword coverage
    matched: list[WeightedSkill] = []
    missing: list[WeightedSkill] = []
    for skill in effective_job.weighted_skills:
        if _keyword_pattern(skill.keyword).search(searchable_text):
            matched.append(skill)
        else:
            missing.append(skill)

    total_weight = sum(s.weight for s in effective_job.weighted_skills)
    matched_weight = sum(s.weight for s in matched)
    if total_weight > 0:
        keyword_score = round((matched_weight / total_weight) * 100.0, 1)
    else:
        keyword_score = 50.0

    # 2. Seniority & expected work alignment (4-8 YoE signals)
    target_signals = job.detected_signals or list(SENIOR_SIGNALS)
    matched_signals = [sig for sig in target_signals if _keyword_pattern(sig).search(searchable_text)]
    seniority_score = (
        round((len(matched_signals) / len(target_signals)) * 100.0, 1)
        if target_signals
        else 75.0
    )

    # 3. Bullet quality (Google XYZ metrics + strong action verbs + humanizer check)
    bullet_cfg = rules.bullet_quality
    humanizer_cfg = rules.humanizer_guardrails
    strong_verbs = {str(v).lower() for v in bullet_cfg.get("strong_action_verbs", [])}
    weak_phrases = [str(w).lower() for w in bullet_cfg.get("weak_phrases", [])]
    ai_slop_words = [str(w).lower() for w in humanizer_cfg.get("ai_slop_banlist", [])]
    max_chars = int(bullet_cfg.get("max_bullet_chars", 220))

    diagnostics: list[BulletDiagnostic] = []
    for exp in resume.experience:
        for bullet in exp.bullets:
            if bullet.approved:
                diagnostics.append(
                    _evaluate_bullet(
                        "Experience",
                        f"{exp.title} @ {exp.company}",
                        bullet.text,
                        strong_verbs,
                        weak_phrases,
                        ai_slop_words,
                        max_chars,
                    )
                )
    for proj in resume.projects:
        for bullet in proj.bullets:
            if bullet.approved:
                diagnostics.append(
                    _evaluate_bullet(
                        "Projects",
                        proj.name,
                        bullet.text,
                        strong_verbs,
                        weak_phrases,
                        ai_slop_words,
                        max_chars,
                    )
                )

    if diagnostics:
        quant_count = sum(1 for d in diagnostics if d.has_quantified_metric)
        quant_ratio = quant_count / len(diagnostics)
        min_quant_ratio = float(bullet_cfg.get("min_quantified_bullet_ratio", 0.45))
        bullet_points = 0.0
        for diag in diagnostics:
            pts = 0.0
            if diag.has_strong_verb:
                pts += 0.35
            # Reward quantified metrics OR substantive architectural/stack bullets once healthy portfolio metric balance exists
            has_concrete_tech = len(diag.bullet_text) >= 48 and (
                re.search(r"[A-Z][a-zA-Z0-9+#./]{1,}", diag.bullet_text[1:]) is not None
            )
            if diag.has_quantified_metric:
                pts += 0.45
            elif has_concrete_tech and quant_ratio >= (min_quant_ratio * 0.7):
                pts += 0.40
            elif has_concrete_tech:
                pts += 0.25
            if not diag.weak_phrases_found and not diag.ai_slop_found:
                pts += 0.20
            bullet_points += min(1.0, pts)
        bullet_score = round((bullet_points / len(diagnostics)) * 100.0, 1)
    else:
        bullet_score = 0.0

    # 4. ATS formatting & page budget check
    format_warnings: list[str] = []
    if not resume.experience:
        format_warnings.append("Missing Experience section.")
    if not resume.skills:
        format_warnings.append("Missing Technical Skills section.")
    if not resume.education:
        format_warnings.append("Missing Education section.")
    if resume.summary and rules.ats_formatting.get("disallow_summary_by_default", False):
        format_warnings.append("Summary/Objective block present; configured rules discourage it.")
    if total_weight == 0:
        format_warnings.append(
            f"No keywords from track '{job.role_track}' appeared in JD; expand your role keyword pack."
        )

    estimated_lines = (
        4
        + (3 if resume.summary else 0)
        + len(resume.education) * 2
        + len(resume.experience) * 2
        + sum(max(1, math.ceil(len(d.bullet_text) / 92)) for d in diagnostics)
        + len(resume.projects) * 2
        + len(resume.certifications)
        + len(resume.skills)
    )
    exact_pages = estimated_lines / 48.0
    estimated_pages = max(1, math.ceil(max(0.0, exact_pages - 0.12)))
    allowed_budget = float(settings.page_budget or 1.5)
    if exact_pages > allowed_budget + 0.18:
        format_warnings.append(
            f"Estimated {exact_pages:.1f} page(s) exceeds configured page_budget ({settings.page_budget})."
        )

    slop_count = sum(len(d.ai_slop_found) for d in diagnostics)
    if slop_count > 0:
        format_warnings.append(f"Humanizer flagged {slop_count} AI-cliché term(s) across bullets.")

    format_score = max(0.0, 100.0 - len(format_warnings) * 20.0)

    weights = rules.scoring_weights
    w_kw = float(weights.get("weighted_keyword_coverage", 0.45))
    w_sen = float(weights.get("seniority_and_work_alignment", 0.25))
    w_bul = float(weights.get("bullet_impact_and_xyz", 0.20))
    w_fmt = float(weights.get("ats_format_and_budget", 0.10))

    overall = round(
        keyword_score * w_kw
        + seniority_score * w_sen
        + bullet_score * w_bul
        + format_score * w_fmt,
        1,
    )

    missing.sort(key=lambda item: (-item.weight, -item.jd_mentions, item.keyword.lower()))
    matched.sort(key=lambda item: (-item.weight, item.keyword.lower()))
    resume_skills = extract_all_resume_skills(resume, searchable_text)
    missing_requirements = build_missing_requirements(
        job=effective_job,
        missing_skills=missing,
        resume_text=searchable_text,
    )

    return ATSReport(
        job_id=job_id,
        resume_id=resume_id,
        overall_score=overall,
        sub_scores={
            "weighted_keyword_coverage": keyword_score,
            "seniority_and_work_alignment": seniority_score,
            "bullet_impact_and_xyz": bullet_score,
            "ats_format_and_budget": format_score,
        },
        matched_skills=matched,
        missing_skills=missing,
        resume_skills=resume_skills,
        missing_requirements=missing_requirements,
        bullet_diagnostics=diagnostics,
        format_warnings=format_warnings,
        estimated_pages=estimated_pages,
    )
