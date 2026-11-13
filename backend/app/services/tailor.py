"""Tailoring preview, location adapter, JD-driven section optimization, and humanizer gate."""

from __future__ import annotations

import copy
import re
from typing import Any

import httpx

from backend.app.schemas.config import AppSettings, BigTechRulesConfig
from backend.app.schemas.job import (
    BulletComparison,
    ExperienceComparison,
    FieldChange,
    JobAnalysis,
    TailorPreviewResponse,
    TailoringReasoningStep,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.jd_analyzer import _keyword_pattern
from backend.app.services.llm_tailor import (
    _add_skills_to_categories,
    _build_tailored_summary,
    _collect_matched_keywords,
    _enforce_experience_bullet_count,
    humanize_bullet_text,
    humanize_resume,
    llm_tailor_with_reasoning,
    normalize_tech_capitalization,
)
from backend.app.services.reasoning_tailor import (
    calibrate_resume_to_ats_band,
    run_reasoning_tailor_script,
)
from backend.app.services.resume_parser import resume_to_plain_text
from backend.app.services.sanity_checker import run_resume_sanity_check
from backend.app.services.skill_enrichment import (
    compute_smart_seniority_sizing,
    enrich_job_weighted_skills,
    filter_engineering_expected_work,
)


def _clean_bullet_humanizer(
    text: str,
    rules: BigTechRulesConfig | None = None,
    avoided_words: list[str] | None = None,
) -> tuple[str, list[str]]:
    updated, labels = humanize_bullet_text(text, rules=rules, avoided_words=avoided_words)
    notes = [f"Humanizer cleaned avoided phrasing: '{lbl}'" for lbl in labels]
    return updated, notes


def _normalize_city_state(location: str) -> str:
    cleaned = re.sub(r"\s*\((?:hybrid|onsite|on-site|remote|in-office)[^)]*\)", "", location, flags=re.I)
    return cleaned.strip(" ,-|")


def build_tailor_preview(
    job_id: int,
    resume_id: int,
    resume_name: str,
    base_resume: CanonicalResume,
    job: JobAnalysis,
    rules: BigTechRulesConfig,
    settings: AppSettings,
    raw_resume_text: str = "",
    job_raw_text: str = "",
    adapt_location: bool = True,
    use_llm: bool | None = None,
    tailor_strategy: str = "auto",
    rehumanize: bool = False,
    bullets_per_experience: int | None = None,
    bullets_per_role_counts: list[int] | None = None,
    bullets_per_project: int | None = None,
    auto_size: bool = False,
    page_budget: float | None = None,
    avoided_words: list[str] | None = None,
    custom_instructions: str | None = None,
    target_score: int = 80,
    target_score_min: int = 80,
    target_score_max: int = 85,
    llm_model: str | None = None,
    ollama_client: httpx.Client | None = None,
    target_sections: list[str] | None = None,
) -> TailorPreviewResponse:
    """Create a deeply tailored, humanized, sanity-checked resume preview calibrated to 80-85% ATS fit."""
    clean_expected = filter_engineering_expected_work(job.expected_work or [])
    effective_job = job.model_copy(
        update={
            "expected_work": clean_expected,
            "weighted_skills": (
                enrich_job_weighted_skills(job_raw_text, job.weighted_skills)
                if job_raw_text and job_raw_text.strip()
                else job.weighted_skills
            ),
        }
    )

    auto_budget, auto_counts, _ = compute_smart_seniority_sizing(effective_job, base_resume)
    effective_page_budget = (
        page_budget
        if page_budget is not None
        else (auto_budget if auto_size else float(settings.page_budget))
    )
    effective_avoided = avoided_words if avoided_words is not None else list(settings.avoided_ai_words)
    settings_updates: dict[str, Any] = {"page_budget": effective_page_budget}
    if llm_model and llm_model.strip():
        settings_updates["llm_model"] = llm_model.strip()
    effective_settings = settings.model_copy(update=settings_updates)

    band_min = max(50, min(target_score_min, target_score_max))
    band_max = max(band_min, target_score_max)

    base_report = score_resume_against_job(
        job_id=job_id,
        resume_id=resume_id,
        resume=base_resume,
        job=effective_job,
        rules=rules,
        settings=effective_settings,
        raw_resume_text=raw_resume_text,
    )

    orig_bullets_by_exp: list[list[str]] = [
        [b.text for b in exp.bullets] for exp in base_resume.experience
    ]
    orig_summary = (base_resume.summary or "").strip()

    tailored = copy.deepcopy(base_resume)
    field_changes: list[FieldChange] = []

    normalized_job_loc = _normalize_city_state(effective_job.location)
    if (
        adapt_location
        and normalized_job_loc
        and normalized_job_loc.lower() != "remote"
        and normalized_job_loc.lower() != (tailored.contact.location or "").strip().lower()
    ):
        before_loc = tailored.contact.location or "(Not set)"
        tailored.contact.location = normalized_job_loc
        field_changes.append(
            FieldChange(
                field_name="Header Location",
                before=before_loc,
                after=normalized_job_loc,
                reason="Aligned candidate location to match target job posting.",
            )
        )

    strategy = (tailor_strategy or "ollama").strip().lower()
    if strategy == "fallback_script" or use_llm is False:
        should_use_llm = False
    elif strategy in ("claude", "ollama", "auto") or use_llm is True:
        should_use_llm = True
    else:
        should_use_llm = effective_settings.llm_mode in ("ollama_local", "ollama_docker")

    tailor_mode: str = "fallback_script"
    model_used: str | None = None
    humanized_count = 0
    all_humanizer_notes: list[str] = []
    llm_notice: str | None = None
    added_jd_skills: list[str] = []
    reasoning_steps: list[TailoringReasoningStep] = []
    resolved_counts: list[int] = list(bullets_per_role_counts or auto_counts)

    if should_use_llm:
        (
            tailored,
            model_used,
            llm_h_count,
            llm_notes,
            llm_notice,
            added_jd_skills,
            reasoning_steps,
            resolved_counts,
            effective_page_budget,
        ) = llm_tailor_with_reasoning(
            base_resume=tailored,
            job=effective_job,
            missing_skills=base_report.missing_skills,
            matched_skills=base_report.matched_skills,
            rules=rules,
            settings=effective_settings,
            job_raw_text=job_raw_text,
            missing_requirements=base_report.missing_requirements,
            bullets_per_experience=bullets_per_experience,
            bullets_per_role_counts=bullets_per_role_counts,
            auto_size=auto_size,
            page_budget=effective_page_budget,
            avoided_words=effective_avoided,
            custom_instructions=custom_instructions,
            target_score=band_min,
            target_score_min=band_min,
            target_score_max=band_max,
            client=ollama_client,
            engine_type=strategy,
            target_sections=target_sections,
        )
        humanized_count += llm_h_count
        all_humanizer_notes.extend(llm_notes)
        if strategy == "claude":
            tailor_mode = "claude"
            if not model_used:
                model_used = "claude-3-5-sonnet"
        elif model_used:
            tailor_mode = "ollama_llm"
        else:
            tailor_mode = "fallback_script"
            if strategy == "ollama" and not llm_notice:
                llm_notice = "Local Ollama could not complete generation; Fallback Reasoning Script completed the tailoring safely."
    else:
        base_kws = _collect_matched_keywords(tailored, effective_job.weighted_skills)
        tailored, _, reasoning_steps, resolved_counts, effective_page_budget, _ = run_reasoning_tailor_script(
            base_resume=tailored,
            job=effective_job,
            rules=rules,
            settings=effective_settings,
            adapt_location=adapt_location,
            bullets_per_experience=bullets_per_experience,
            bullets_per_role_counts=bullets_per_role_counts,
            auto_size=auto_size,
            page_budget=effective_page_budget,
            target_score_min=band_min,
            target_score_max=band_max,
            normalize_fn=normalize_tech_capitalization,
            add_skills_fn=_add_skills_to_categories,
            enforce_count_fn=_enforce_experience_bullet_count,
            summary_fn=_build_tailored_summary,
        )
        tailored_kws = _collect_matched_keywords(tailored, effective_job.weighted_skills)
        added_jd_skills = [
            ws.keyword
            for ws in effective_job.weighted_skills
            if ws.keyword.lower() not in base_kws and ws.keyword.lower() in tailored_kws
        ]
        tailored, det_h_count, det_notes = humanize_resume(
            tailored,
            rules=rules,
            avoided_words=effective_avoided,
        )
        humanized_count += det_h_count + len(added_jd_skills)
        all_humanizer_notes.extend(det_notes)
        if strategy == "fallback_script":
            llm_notice = "Executed standalone multi-step Fallback Reasoning Script."

    # Always run humanizer pass cleanly in the unified tailoring step
    tailored, extra_h_count, extra_notes = humanize_resume(
        tailored,
        rules=rules,
        avoided_words=effective_avoided,
    )
    humanized_count += extra_h_count
    all_humanizer_notes.extend(extra_notes)

    effective_settings = effective_settings.model_copy(update={"page_budget": effective_page_budget})

    # Pre-sanity score so sanity check sees exact calibrated match
    pre_sanity_report = score_resume_against_job(
        job_id=job_id,
        resume_id=resume_id,
        resume=tailored,
        job=effective_job,
        rules=rules,
        settings=effective_settings,
        raw_resume_text=resume_to_plain_text(tailored),
    )

    # Integrated Real-World Plausibility & Timeline Sanity Check
    tailored, sanity_checks, sanity_passed, sanity_summary = run_resume_sanity_check(
        base_resume=base_resume,
        tailored_resume=tailored,
        job=effective_job,
        tailored_report=pre_sanity_report,
        avoided_words=effective_avoided,
        target_score_min=band_min,
        target_score_max=band_max,
    )

    # Re-apply header location if adapted cleanly (anchor lock preserves company/title/dates/edu, not contact location)
    if (
        adapt_location
        and normalized_job_loc
        and normalized_job_loc.lower() != "remote"
        and normalized_job_loc.lower() != (base_resume.contact.location or "").strip().lower()
    ):
        tailored.contact.location = normalized_job_loc

    # Enforce configured project bullet count if specified
    if bullets_per_project is not None and bullets_per_project > 0:
        for proj in tailored.projects:
            if len(proj.bullets) > bullets_per_project:
                proj.bullets = proj.bullets[:bullets_per_project]

    # Record high-level Summary & Added JD Skills changes for optional diff audit
    new_summary = (tailored.summary or "").strip()
    if new_summary and new_summary != orig_summary:
        field_changes.append(
            FieldChange(
                field_name="Professional Summary",
                before=orig_summary or "(None)",
                after=new_summary,
                reason=f"Tailored opener specifically around {effective_job.title} at {effective_job.company}.",
            )
        )
    if added_jd_skills:
        field_changes.append(
            FieldChange(
                field_name="JD Skills Integrated",
                before="—",
                after=", ".join(added_jd_skills),
                reason="Added missing JD skills across Summary, Projects, Experience, and Technical Skills.",
            )
        )

    experience_comparisons: list[ExperienceComparison] = []
    for exp_idx, exp in enumerate(tailored.experience):
        orig_texts = orig_bullets_by_exp[exp_idx] if exp_idx < len(orig_bullets_by_exp) else []
        scored_bullets: list[tuple[float, int, BulletComparison]] = []
        for idx, bullet in enumerate(exp.bullets):
            is_new_bullet = idx >= len(orig_texts)
            original_text = "(New bullet generated for JD requirements)" if is_new_bullet else orig_texts[idx]
            cleaned_text, bullet_notes = _clean_bullet_humanizer(
                bullet.text,
                rules=rules,
                avoided_words=effective_avoided,
            )
            if cleaned_text != bullet.text:
                bullet.text = cleaned_text
                humanized_count += 1

            matched_kws = [
                ws.keyword
                for ws in effective_job.weighted_skills
                if _keyword_pattern(ws.keyword).search(cleaned_text)
            ]
            relevance_score = sum(
                ws.weight
                for ws in effective_job.weighted_skills
                if _keyword_pattern(ws.keyword).search(cleaned_text)
            )
            if is_new_bullet or cleaned_text != original_text:
                if bullet.provenance == "VERIFIED_BASE":
                    bullet.provenance = "REFRAMED"
                bullet_status: str = (
                    "edited"
                    if is_new_bullet
                    or (
                        model_used
                        and (abs(len(cleaned_text) - len(original_text)) > 12 or not bullet_notes)
                    )
                    else "polished"
                )
            else:
                bullet_status = "unchanged"

            if model_used and (is_new_bullet or cleaned_text != original_text):
                bullet_notes = [f"Tailored with {model_used}", *bullet_notes]
            elif not model_used and (is_new_bullet or cleaned_text != original_text):
                bullet_notes = ["Tailored via Fallback Reasoning Script", *bullet_notes]

            scored_bullets.append(
                (
                    relevance_score,
                    idx,
                    BulletComparison(
                        bullet_id=bullet.id or f"{exp.id}_b{idx + 1}",
                        original_text=original_text,
                        tailored_text=cleaned_text,
                        status=bullet_status,  # type: ignore[arg-type]
                        matched_keywords=matched_kws,
                        notes=bullet_notes,
                    ),
                )
            )

        reordered = sorted(scored_bullets, key=lambda item: (-item[0], item[1]))
        new_order_indices = [item[1] for item in reordered]
        order_changed = new_order_indices != list(range(len(exp.bullets)))
        if order_changed and exp.bullets:
            exp.bullets = [exp.bullets[i] for i in new_order_indices]

        comparisons: list[BulletComparison] = []
        for pos, (_, orig_idx, comp) in enumerate(reordered):
            if order_changed and orig_idx != pos and comp.status == "unchanged":
                comp.status = "reordered"
                comp.notes.append(f"Moved up from #{orig_idx + 1} to #{pos + 1} for JD skill relevance")
            elif order_changed and orig_idx != pos:
                comp.notes.append(f"Prioritized from #{orig_idx + 1} to #{pos + 1} for JD relevance")
            comparisons.append(comp)

        dates = f"{exp.start_date} - {exp.end_date}".strip(" -")
        experience_comparisons.append(
            ExperienceComparison(
                experience_id=exp.id or exp.company,
                company=exp.company,
                title=exp.title,
                dates=dates,
                bullets=comparisons,
            )
        )

    tailored_report = score_resume_against_job(
        job_id=job_id,
        resume_id=resume_id,
        resume=tailored,
        job=effective_job,
        rules=rules,
        settings=effective_settings,
        raw_resume_text=resume_to_plain_text(tailored),
    )

    # Post-humanizer / post-sanity final guard: ensure final score sits strictly inside [band_min, band_max]
    if not (band_min <= tailored_report.overall_score <= band_max):
        extra_cal_steps: list[TailoringReasoningStep] = []
        tailored, _, extra_cal = calibrate_resume_to_ats_band(
            draft=tailored,
            base_resume=base_resume,
            job=effective_job,
            rules=rules,
            settings=effective_settings,
            target_score_min=band_min,
            target_score_max=band_max,
            add_skills_fn=_add_skills_to_categories,
            normalize_fn=normalize_tech_capitalization,
            steps_log=extra_cal_steps,
        )
        tailored, _, _ = humanize_resume(tailored, rules=rules, avoided_words=effective_avoided)
        tailored_report = score_resume_against_job(
            job_id=job_id,
            resume_id=resume_id,
            resume=tailored,
            job=effective_job,
            rules=rules,
            settings=effective_settings,
            raw_resume_text=resume_to_plain_text(tailored),
        )
        for chk in sanity_checks:
            if chk.check_id == "ats_band":
                in_b = band_min <= tailored_report.overall_score <= band_max
                chk.status = "passed" if in_b else "warning"
                chk.detail = (
                    f"Calibrated ATS match {tailored_report.overall_score:.1f}% sits cleanly inside target {band_min}-{band_max}% range."
                    if in_b
                    else f"ATS match is {tailored_report.overall_score:.1f}% (target {band_min}-{band_max}%)."
                )
        if extra_cal:
            for step in reversed(reasoning_steps):
                if "Calibration" in step.phase:
                    step.decision = f"Calibrated tailored match to {tailored_report.overall_score:.1f}% (target {band_min}-{band_max}%)."
                    break

    in_band = band_min <= tailored_report.overall_score <= band_max

    return TailorPreviewResponse(
        job_id=job_id,
        resume_id=resume_id,
        resume_name=resume_name,
        base_score=base_report.overall_score,
        tailored_score=tailored_report.overall_score,
        base_report=base_report,
        tailored_report=tailored_report,
        field_changes=field_changes,
        experience_comparisons=experience_comparisons,
        tailored_resume=tailored,
        tailor_mode=tailor_mode,  # type: ignore[arg-type]
        model_used=model_used,
        humanized_count=humanized_count,
        humanizer_notes=list(dict.fromkeys(all_humanizer_notes))[:12],
        llm_notice=llm_notice,
        added_jd_skills=added_jd_skills,
        target_score_met=tailored_report.overall_score >= band_min,
        target_score_min=band_min,
        target_score_max=band_max,
        in_target_band=in_band,
        bullets_per_experience=bullets_per_experience,
        bullets_per_role_counts=resolved_counts,
        bullets_per_project=bullets_per_project,
        page_budget=effective_page_budget,
        reasoning_steps=reasoning_steps,
        sanity_checks=sanity_checks,
        sanity_passed=sanity_passed,
        sanity_summary=sanity_summary,
    )
