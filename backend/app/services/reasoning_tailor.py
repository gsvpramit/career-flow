"""Multi-step deterministic Reasoning Tailoring Engine & 80%-85% ATS Score Calibrator."""

from __future__ import annotations

import copy
import re
from typing import Callable, Sequence

from backend.app.schemas.config import AppSettings, BigTechRulesConfig
from backend.app.schemas.job import ATSReport, JobAnalysis, TailoringReasoningStep, WeightedSkill
from backend.app.schemas.resume import CanonicalResume, ExperienceBullet, ExperienceItem, ProjectItem, SkillCategory
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.jd_analyzer import _keyword_pattern
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.sanity_checker import TECH_ERA_FLOOR_YEAR, _extract_end_year
from backend.app.services.skill_enrichment import compute_smart_seniority_sizing


def _reframe_bullet_with_skills(
    text: str,
    skills_to_weave: Sequence[str],
    normalize_fn: Callable[[str], str],
    exp_end_year: int = 2026,
) -> tuple[str, list[str]]:
    """Weave compatible missing JD skills into a bullet naturally while respecting era chronology."""
    clean = (text or "").strip()
    if not clean or not skills_to_weave:
        return clean, []

    compatible: list[str] = []
    for raw_sk in skills_to_weave:
        sk = normalize_fn(raw_sk.strip())
        if not sk:
            continue
        floor_yr = TECH_ERA_FLOOR_YEAR.get(sk.lower(), 2010)
        if exp_end_year < floor_yr:
            continue
        if _keyword_pattern(sk).search(clean):
            continue
        compatible.append(sk)
        if len(compatible) >= 2:
            break

    if not compatible:
        return clean, []

    base_no_dot = clean.rstrip(" .;")
    if len(base_no_dot) > 195:
        return clean, []

    stack_phrase = " and ".join(compatible)
    # Attach stack cleanly before trailing metric/impact clause or at the end of sentence cleanly
    tail_connectors = [
        f"{base_no_dot}, incorporating {stack_phrase} across production workflows.",
        f"{base_no_dot} backed by {stack_phrase} services and automated validation.",
    ]
    chosen = tail_connectors[0] if len(base_no_dot) < 165 else f"{base_no_dot} using {stack_phrase}."
    return chosen, compatible


FOUNDATIONAL_CORE_SKILLS: frozenset[str] = frozenset(
    {
        "python",
        "java",
        "typescript",
        "javascript",
        "go",
        "sql",
        "postgresql",
        "mysql",
        "redis",
        "aws",
        "gcp",
        "docker",
        "kubernetes",
        "terraform",
        "git",
        "ci/cd",
        "rest apis",
        "fastapi",
        "kafka",
        "spark",
        "pyspark",
        "airflow",
        "pytorch",
        "llm",
        "llms",
        "rag",
    }
)


NON_TECHNICAL_SOFT_WORDS: set[str] = {
    "mentorship",
    "technical leadership",
    "leadership",
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


def curate_heavy_resume_sections(
    *,
    draft: CanonicalResume,
    job: JobAnalysis,
    normalize_fn: Callable[[str], str],
    max_skills_total: int = 56,
    max_projects: int = 3,
) -> tuple[CanonicalResume, list[str], int]:
    """Curate heavy multi-year resumes: keep foundational & JD-relevant skills/projects, prune off-track bloat."""
    updated = draft.model_copy(deep=True)
    jd_kw_map = {ws.keyword.strip().lower(): float(ws.weight) for ws in (job.weighted_skills or [])}

    # First clean out non-technical buzzwords from all technical skill categories
    for cat in updated.skills:
        cat.items = [
            item for item in cat.items
            if item.strip().lower() not in NON_TECHNICAL_SOFT_WORDS
        ]

    # Prune excessive skills (> max_skills_total) while preserving rich senior skills
    total_before = sum(len(c.items) for c in updated.skills)
    pruned_skills: list[str] = []
    if total_before > max_skills_total:
        scored: list[tuple[float, int, int, str, str]] = []
        for c_idx, cat in enumerate(updated.skills):
            for s_idx, item in enumerate(cat.items):
                clean = normalize_fn(item.strip())
                low = clean.lower()
                jd_w = jd_kw_map.get(low, 0.0)
                if jd_w == 0.0:
                    for jk, w in jd_kw_map.items():
                        if len(jk) >= 3 and (jk in low or low in jk):
                            jd_w = max(jd_w, w * 0.85)
                foundational_bonus = 6.0 if low in FOUNDATIONAL_CORE_SKILLS else 0.0
                score = jd_w * 2.0 + foundational_bonus + (0.05 if s_idx < 4 else 0.0)
                scored.append((score, -c_idx, -s_idx, cat.category, clean))

        scored.sort(reverse=True)
        keep_pairs = {(cat_name, sk.lower()) for _, _, _, cat_name, sk in scored[:max_skills_total]}
        new_cats = []
        seen_global: set[str] = set()
        for cat in updated.skills:
            kept_items: list[str] = []
            for raw in cat.items:
                clean = normalize_fn(raw.strip())
                low = clean.lower()
                if not clean or low in seen_global:
                    continue
                if (cat.category, low) in keep_pairs or low in jd_kw_map:
                    kept_items.append(clean)
                    seen_global.add(low)
                else:
                    pruned_skills.append(clean)
            if kept_items:
                cat.items = kept_items
                new_cats.append(cat)
        updated.skills = new_cats

    # Curate heavy project lists (> max_projects) keeping highest JD overlap projects
    pruned_proj_count = 0
    if len(updated.projects) > max_projects:
        scored_projs: list[tuple[float, int, ProjectItem]] = []
        for idx, proj in enumerate(updated.projects):
            p_text = " ".join([proj.name, *proj.tech_stack, *(b.text for b in proj.bullets)]).lower()
            overlap = sum(w for jk, w in jd_kw_map.items() if jk in p_text)
            scored_projs.append((overlap, -idx, proj))
        scored_projs.sort(reverse=True)
        chosen_indices = {(-neg_idx) for _, neg_idx, _ in scored_projs[:max_projects]}
        pruned_proj_count = len(updated.projects) - len(chosen_indices)
        updated.projects = [p for i, p in enumerate(updated.projects) if i in chosen_indices]

    return updated, pruned_skills, pruned_proj_count


def _tailor_projects_to_jd(
    *,
    projects: list[ProjectItem],
    job: JobAnalysis,
    priority_skills: Sequence[str],
    normalize_fn: Callable[[str], str],
) -> tuple[list[ProjectItem], list[str]]:
    """Tailor at least 2 projects to highlight JD technologies while preserving authentic project identity."""
    missing_clean = [normalize_fn(s.strip()) for s in priority_skills if s.strip()]
    primary_stack = missing_clean[:4] or ["Python", "FastAPI", "Docker", "PostgreSQL"]
    secondary_stack = (missing_clean[3:7] or missing_clean[:4] or ["AWS", "Redis", "Kubernetes", "CI/CD"])

    updated: list[ProjectItem] = [p.model_copy(deep=True) for p in projects]
    woven: list[str] = []

    def _enrich_existing_project(proj: ProjectItem, seed_stack: list[str], focus_idx: int) -> None:
        merged_stack = list(dict.fromkeys([*(normalize_fn(t) for t in proj.tech_stack if t.strip()), *seed_stack[:3]]))[:7]
        # Keep top JD tools first while retaining base tools
        ordered_stack = list(dict.fromkeys([*seed_stack[:3], *merged_stack]))[:7]
        proj.tech_stack = ordered_stack
        woven.extend(seed_stack[:3])
        if not proj.bullets:
            proj.bullets = [
                ExperienceBullet(
                    id=f"{proj.id or f'proj{focus_idx}'}_b1",
                    text=(
                        f"Built modular {ordered_stack[0]} service components using {', '.join(ordered_stack[1:4] or ['Docker'])} "
                        f"tailored for {job.title or 'production'} workloads and automated integration verification."
                    ),
                    provenance="REFRAMED",
                    approved=True,
                    tags=ordered_stack[:3],
                ),
                ExperienceBullet(
                    id=f"{proj.id or f'proj{focus_idx}'}_b2",
                    text=(
                        f"Instrumented observability, schema checks, and fault-tolerant execution across {', '.join(ordered_stack[:3])}."
                    ),
                    provenance="REFRAMED",
                    approved=True,
                    tags=ordered_stack[:3],
                ),
            ]
            return

        # Reframe first 1-2 bullets authentically instead of wiping original project achievements
        need_terms = [t for t in seed_stack[:3] if not any(_keyword_pattern(t).search(b.text) for b in proj.bullets)]
        if need_terms:
            target_b = proj.bullets[0]
            cleaned_base = target_b.text.rstrip(".")
            if len(cleaned_base) > 155:
                cleaned_base = cleaned_base[:150].rsplit(" ", 1)[0]
            target_b.text = f"{cleaned_base} using {', '.join(need_terms[:2])}."
            target_b.provenance = "REFRAMED"
            target_b.tags = list(dict.fromkeys([*target_b.tags, *need_terms[:2]]))
        for b in proj.bullets:
            b.text = normalize_fn(b.text)

    if len(updated) >= 1:
        _enrich_existing_project(updated[0], primary_stack, 1)
    else:
        updated.append(
            ProjectItem(
                id="tailor_proj_1",
                name="Aiceberg: Production LLM Guardrail & Evaluation Engine",
                tech_stack=primary_stack,
                link="github.com/portfolio/aiceberg-evals",
                bullets=[
                    ExperienceBullet(
                        id="tp1_b1",
                        text=f"Engineered high-throughput inference guardrails using {primary_stack[0]} and {', '.join(primary_stack[1:3] or ['Docker'])}, validating structured schemas with sub-50ms latency.",
                        provenance="SUGGESTED_DRAFT",
                        approved=True,
                        tags=primary_stack[:3],
                    ),
                    ExperienceBullet(
                        id="tp1_b2",
                        text=f"Implemented automated evaluation suites and reproducible benchmarks across {', '.join(primary_stack[:3])}.",
                        provenance="SUGGESTED_DRAFT",
                        approved=True,
                        tags=primary_stack[:3],
                    ),
                ],
            )
        )
        woven.extend(primary_stack[:3])

    if len(updated) >= 2:
        _enrich_existing_project(updated[1], secondary_stack, 2)
    else:
        updated.append(
            ProjectItem(
                id="tailor_proj_2",
                name="SmartClass: Distributed Serverless Event & Inference Pipeline",
                tech_stack=secondary_stack,
                link="github.com/portfolio/smartclass-pipeline",
                bullets=[
                    ExperienceBullet(
                        id="tp2_b1",
                        text=f"Engineered event-driven workers with {', '.join(secondary_stack[:3])} supporting replayable state recovery and structured observability.",
                        provenance="SUGGESTED_DRAFT",
                        approved=True,
                        tags=secondary_stack[:3],
                    ),
                    ExperienceBullet(
                        id="tp2_b2",
                        text=f"Automated CI contract tests and resource telemetry across {', '.join(secondary_stack[:3])}.",
                        provenance="SUGGESTED_DRAFT",
                        approved=True,
                        tags=secondary_stack[:3],
                    ),
                ],
            )
        )
        woven.extend(secondary_stack[:3])

    return updated, list(dict.fromkeys(woven))


def _remove_kw_from_text_cleanly(text: str, kw: str) -> str:
    """Remove a specific over-stuffed keyword from tailored prose while preserving grammar."""
    if not text or not kw:
        return text
    pat = _keyword_pattern(kw)
    if not pat.search(text):
        return text
    # Handle comma/conjunction lists first so punctuation stays crisp
    escaped = pat.pattern
    cleaned = re.sub(rf"\s*,\s*and\s+{escaped}\b", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\b(?:incorporating|using|across|via|including)\s+{escaped}(?=\s|[.,;]|$)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"{escaped}\s*,\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\s*,\s*{escaped}", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\s+and\s+{escaped}\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(rf"\b{escaped}\s+and\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = pat.sub("", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    cleaned = re.sub(r",\s*,+", ",", cleaned)
    cleaned = re.sub(r",\s*\.", ".", cleaned)
    cleaned = cleaned.strip()
    if cleaned and not cleaned.endswith((".", "!", "?")):
        cleaned += "."
    return cleaned


def _de_stuff_keyword_trial(
    working: CanonicalResume,
    base_resume: CanonicalResume,
    kw: str,
) -> CanonicalResume | None:
    """Return a copy of working with keyword kw gracefully toned down, preserving core structure."""
    trial = working.model_copy(deep=True)
    changed = False

    # 1. Remove from Technical Skills while keeping rich senior skill floor (>= 14 when base is rich)
    base_skill_count = sum(len(c.items) for c in base_resume.skills)
    min_skills_floor = min(14, max(6, base_skill_count - 4))
    total_skills = sum(len(c.items) for c in trial.skills)
    if kw.strip().lower() not in FOUNDATIONAL_CORE_SKILLS or total_skills > (min_skills_floor + 4):
        for cat in trial.skills:
            filtered = [item for item in cat.items if item.strip().lower() != kw.lower()]
            if len(filtered) != len(cat.items) and (total_skills - (len(cat.items) - len(filtered))) >= min_skills_floor:
                cat.items = filtered
                total_skills = sum(len(c.items) for c in trial.skills)
                changed = True
    trial.skills = [c for c in trial.skills if c.items]

    # 2. Revert any REFRAMED experience bullet carrying kw back to its original base phrasing if clean
    base_bullet_lookup = {
        b.id: b.text
        for exp in base_resume.experience
        for b in exp.bullets
        if b.id
    }
    for exp in trial.experience:
        for b in exp.bullets:
            if _keyword_pattern(kw).search(b.text):
                if b.provenance == "REFRAMED" and b.id in base_bullet_lookup and not _keyword_pattern(kw).search(base_bullet_lookup[b.id]):
                    b.text = base_bullet_lookup[b.id]
                    b.provenance = "VERIFIED_BASE"
                    changed = True
                elif b.provenance != "VERIFIED_BASE":
                    b.text = _remove_kw_from_text_cleanly(b.text, kw)
                    changed = True
                else:
                    # Even verified base bullets can generalize one over-indexed niche token if needed
                    b.text = _remove_kw_from_text_cleanly(b.text, kw)
                    changed = True

    # 3. Generalize Projects tech_stack / bullets for kw
    for proj in trial.projects:
        filtered_stack = [t for t in proj.tech_stack if t.strip().lower() != kw.lower()]
        if len(filtered_stack) != len(proj.tech_stack) and len(filtered_stack) >= 2:
            proj.tech_stack = filtered_stack
            changed = True
        for pb in proj.bullets:
            if _keyword_pattern(kw).search(pb.text):
                pb.text = _remove_kw_from_text_cleanly(pb.text, kw)
                changed = True

    # 4. Generalize Summary mention if present
    if trial.summary and _keyword_pattern(kw).search(trial.summary):
        trial.summary = _remove_kw_from_text_cleanly(trial.summary, kw)
        changed = True

    return trial if changed else None


def calibrate_resume_to_ats_band(
    *,
    draft: CanonicalResume,
    base_resume: CanonicalResume,
    job: JobAnalysis,
    rules: BigTechRulesConfig,
    settings: AppSettings,
    target_score_min: int,
    target_score_max: int,
    add_skills_fn: Callable[[list[SkillCategory], Sequence[str], int], list[str]],
    normalize_fn: Callable[[str], str],
    steps_log: list[TailoringReasoningStep],
) -> tuple[CanonicalResume, ATSReport, list[str]]:
    """Keep tailored ATS match cleanly calibrated inside [target_score_min, target_score_max] (default 80-85%)."""
    working = draft.model_copy(deep=True)
    added_skills: list[str] = []

    def _score(res: CanonicalResume) -> ATSReport:
        return score_resume_against_job(
            job_id=0,
            resume_id=0,
            resume=res,
            job=job,
            rules=rules,
            settings=settings,
            raw_resume_text=resume_to_plain_text(res),
        )

    report = _score(working)
    sweet_midpoint = min(float(target_score_max) - 1.0, float(target_score_min) + 2.5)

    # Phase A: If under target_score_min (e.g. < 80%), incrementally integrate missing skills & signals
    if report.overall_score < target_score_min and report.missing_skills:
        ranked_missing = sorted(report.missing_skills, key=lambda x: (-x.weight, -x.jd_mentions, x.keyword))
        for ws in ranked_missing:
            if report.overall_score >= sweet_midpoint:
                break
            newly = add_skills_fn(working.skills, [ws.keyword], 14)
            if newly:
                added_skills.extend(newly)
                report = _score(working)

    # If still under target_score_min, weave top unmatched JD signals and missing skills cleanly in one natural sentence
    if report.overall_score < target_score_min:
        text_now = resume_to_plain_text(working)
        unmatched_signals = [
            sig for sig in (job.detected_signals or [])
            if not _keyword_pattern(sig).search(text_now)
        ]
        still_missing = [
            normalize_fn(ws.keyword)
            for ws in sorted(report.missing_skills, key=lambda x: -x.weight)[:4]
            if not working.summary or ws.keyword.lower() not in working.summary.lower()
        ]
        extras: list[str] = []
        if unmatched_signals:
            extras.append(", ".join(unmatched_signals[:3]))
        if still_missing:
            extras.append(", ".join(still_missing[:3]))
        if extras and working.summary:
            working.summary = (
                working.summary.rstrip(".")
                + f", with production focus across {' and '.join(extras)}."
            )
            added_skills.extend(still_missing[:3])
            report = _score(working)

    # Phase B: If over-tailored above target_score_max (e.g. > 85%), gently de-stuff lowest-weight terms
    trimmed_for_balance: list[str] = []
    if report.overall_score > target_score_max and report.matched_skills:
        from backend.app.services.skill_enrichment import strip_keyword_from_stacks_and_clean_prose

        # Sort lowest-weight / non-required skills first so core expertise stays front and center
        removable_matched = sorted(
            report.matched_skills,
            key=lambda ws: (ws.in_required_section, ws.weight, ws.jd_mentions, ws.keyword),
        )
        for ws in removable_matched:
            if report.overall_score <= target_score_max:
                break
            trial = _de_stuff_keyword_trial(working, base_resume, ws.keyword)
            cleaned_trial = strip_keyword_from_stacks_and_clean_prose(
                trial or working,
                base_resume,
                ws.keyword,
            )
            trial = cleaned_trial or trial
            if trial is None:
                continue
            trial_report = _score(trial)
            if trial_report.overall_score < float(target_score_min):
                continue
            working = trial
            report = trial_report
            trimmed_for_balance.append(ws.keyword)

    # Phase B2: On sparse JDs where skill weights are chunky, soften excess seniority signals to stay <= 85%
    from backend.app.services.jd_analyzer import SENIOR_SIGNALS

    active_signals = list(job.detected_signals or SENIOR_SIGNALS)
    if report.overall_score > target_score_max and active_signals:
        from backend.app.services.skill_enrichment import soften_signal_on_resume

        matched_skill_lows = {ws.keyword.lower() for ws in report.matched_skills}
        base_text = resume_to_plain_text(base_resume)
        # Prefer signals NOT also tracked as a weighted skill and NOT originally in base_resume
        ordered_signals = sorted(
            active_signals,
            key=lambda sig: (
                sig.lower() in matched_skill_lows,
                bool(_keyword_pattern(sig).search(base_text)),
                sig.lower(),
            ),
        )
        for include_base in (False, True):
            if report.overall_score <= target_score_max:
                break
            for sig in ordered_signals:
                if report.overall_score <= target_score_max:
                    break
                trial = soften_signal_on_resume(
                    working,
                    base_resume,
                    sig,
                    include_base_bullets=include_base,
                )
                if trial is None:
                    continue
                trial_report = _score(trial)
                if trial_report.overall_score < float(target_score_min) or trial_report.overall_score >= report.overall_score:
                    continue
                working = trial
                report = trial_report
                trimmed_for_balance.append(f"signal:{sig}")

    steps_log.append(
        TailoringReasoningStep(
            step=len(steps_log) + 1,
            phase="ATS Band Calibration",
            decision=(
                f"Calibrated tailored match to {report.overall_score}% (target {target_score_min}-{target_score_max}%)"
                + (f"; added {len(added_skills)} skill(s)" if added_skills else "")
                + (f"; toned down {len(trimmed_for_balance)} excess keyword(s) to stay inside band" if trimmed_for_balance else "")
                + "."
            ),
        )
    )
    return working, report, list(dict.fromkeys(added_skills))


def run_reasoning_tailor_script(
    *,
    base_resume: CanonicalResume,
    job: JobAnalysis,
    rules: BigTechRulesConfig,
    settings: AppSettings,
    adapt_location: bool,
    bullets_per_experience: int | None,
    bullets_per_role_counts: Sequence[int] | None,
    auto_size: bool,
    page_budget: float | None,
    target_score_min: int,
    target_score_max: int,
    normalize_fn: Callable[[str], str],
    add_skills_fn: Callable[[list[SkillCategory], Sequence[str], int], list[str]],
    enforce_count_fn: Callable[[ExperienceItem, int, int | None, JobAnalysis, list[str]], None],
    summary_fn: Callable[..., str],
) -> tuple[CanonicalResume, ATSReport, list[TailoringReasoningStep], list[int], float, list[str]]:
    """Execute structured multi-step reasoning tailoring without requiring Ollama."""
    draft = base_resume.model_copy(deep=True)
    draft.education = copy.deepcopy(base_resume.education)
    draft.certifications = copy.deepcopy(base_resume.certifications)

    steps: list[TailoringReasoningStep] = []

    base_report = score_resume_against_job(
        job_id=0,
        resume_id=0,
        resume=draft,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=resume_to_plain_text(draft),
    )

    missing_ordered = [ws.keyword for ws in sorted(base_report.missing_skills, key=lambda x: (-x.weight, -x.jd_mentions))]
    matched_ordered = [ws.keyword for ws in sorted(base_report.matched_skills, key=lambda x: (-x.weight, -x.jd_mentions))]
    priority_skills = [*missing_ordered, *matched_ordered]

    steps.append(
        TailoringReasoningStep(
            step=1,
            phase="JD Gap & Requirement Audit",
            decision=(
                f"Detected {len(base_report.missing_skills)} missing skill(s) "
                f"({', '.join(missing_ordered[:6]) or 'none'}) and {len(base_report.missing_requirements)} unmet requirement signal(s) "
                f"from {job.company} — {job.title}."
            ),
        )
    )

    # Step 2: Resolve variable bullet counts & page budget
    auto_budget, auto_counts, auto_rationale = compute_smart_seniority_sizing(job, draft)
    effective_budget = auto_budget if auto_size else (float(page_budget) if page_budget is not None else auto_budget)

    exp_len = len(draft.experience)
    resolved_counts: list[int] = []
    if bullets_per_role_counts and len(bullets_per_role_counts) > 0:
        for idx in range(exp_len):
            val = bullets_per_role_counts[idx] if idx < len(bullets_per_role_counts) else bullets_per_role_counts[-1]
            resolved_counts.append(max(2, min(10, int(val))))
        sizing_note = f"Using custom per-role bullet profile {resolved_counts} on {effective_budget:g}-page layout."
    elif bullets_per_experience is not None and not auto_size:
        n_uni = max(2, min(10, int(bullets_per_experience)))
        resolved_counts = [n_uni] * exp_len
        sizing_note = f"Using configured {n_uni} bullet(s) per role on {effective_budget:g}-page layout."
    else:
        resolved_counts = auto_counts
        sizing_note = auto_rationale

    steps.append(TailoringReasoningStep(step=2, phase="Length & Bullet Allocation", decision=sizing_note))

    # Step 3: Rewrite Summary specifically for this job
    draft_text = resume_to_plain_text(draft)
    unmatched_signals = [s for s in (job.detected_signals or []) if not _keyword_pattern(s).search(draft_text)]
    draft.summary = summary_fn(
        base_summary=draft.summary,
        job=job,
        key_skills=[*missing_ordered[:5], *matched_ordered[:4]],
        missing_signals=unmatched_signals[:3],
    )
    steps.append(
        TailoringReasoningStep(
            step=3,
            phase="Executive Summary Alignment",
            decision=f"Re-anchored Summary to '{job.title}' at {job.company} incorporating {', '.join(missing_ordered[:4] or matched_ordered[:4])}.",
        )
    )

    # Step 4: Tailor Experience bullets cleanly across employers (respecting locked dates/titles)
    reframed_count = 0
    woven_pool = list(missing_ordered)
    for exp_idx, exp in enumerate(draft.experience):
        orig = base_resume.experience[exp_idx]
        exp.id = orig.id
        exp.company = orig.company
        exp.title = orig.title
        exp.start_date = orig.start_date
        exp.end_date = orig.end_date
        exp.location = orig.location

        target_c = resolved_counts[exp_idx] if exp_idx < len(resolved_counts) else None
        enforce_count_fn(exp, exp_idx, target_c, job, priority_skills)

        end_yr = _extract_end_year(exp)
        bullets_to_modify = min(len(exp.bullets), 3 if exp_idx == 0 else 2)
        for b_idx in range(bullets_to_modify):
            if not woven_pool:
                break
            slice_skills = woven_pool[:2]
            updated_text, used_sk = _reframe_bullet_with_skills(exp.bullets[b_idx].text, slice_skills, normalize_fn, exp_end_year=end_yr)
            if used_sk:
                exp.bullets[b_idx].text = updated_text
                exp.bullets[b_idx].provenance = "REFRAMED"
                exp.bullets[b_idx].tags = list(dict.fromkeys([*exp.bullets[b_idx].tags, *used_sk]))
                for u in used_sk:
                    if u in woven_pool:
                        woven_pool.remove(u)
                reframed_count += 1

    steps.append(
        TailoringReasoningStep(
            step=4,
            phase="Chronology-Safe Experience Reframing",
            decision=f"Reframed {reframed_count} experience bullet(s) across {exp_len} locked employer(s) using variable counts {resolved_counts}.",
        )
    )

    # Step 5: Curate heavy senior resumes cleanly + tailor Projects (>= 2) to JD stack
    draft, pruned_skills, pruned_projs = curate_heavy_resume_sections(
        draft=draft,
        job=job,
        normalize_fn=normalize_fn,
    )
    if pruned_skills or pruned_projs:
        steps.append(
            TailoringReasoningStep(
                step=len(steps) + 1,
                phase="Senior Portfolio Curation",
                decision=(
                    f"Retained core senior stack and pruned {len(pruned_skills)} off-track skill(s)"
                    + (f" and {pruned_projs} lower-relevance project(s)" if pruned_projs else "")
                    + " to match this JD."
                ),
            )
        )

    draft.projects, proj_woven = _tailor_projects_to_jd(
        projects=draft.projects,
        job=job,
        priority_skills=priority_skills,
        normalize_fn=normalize_fn,
    )
    steps.append(
        TailoringReasoningStep(
            step=5,
            phase="Project Portfolio Adaptation",
            decision=f"Updated {len(draft.projects)} projects to spotlight {', '.join(proj_woven[:5])}.",
        )
    )

    # Step 6: ATS Band Calibration (80-85%)
    calibrated, final_report, added_skills = calibrate_resume_to_ats_band(
        draft=draft,
        base_resume=base_resume,
        job=job,
        rules=rules,
        settings=settings,
        target_score_min=target_score_min,
        target_score_max=target_score_max,
        add_skills_fn=add_skills_fn,
        normalize_fn=normalize_fn,
        steps_log=steps,
    )
    return calibrated, final_report, steps, resolved_counts, effective_budget, added_skills
