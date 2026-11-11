"""Tailoring preview, location adapter, humanizer cleanup, and before/after comparison."""

from __future__ import annotations

import copy
import re

from backend.app.schemas.config import AppSettings, BigTechRulesConfig
from backend.app.schemas.job import (
    BulletComparison,
    ExperienceComparison,
    FieldChange,
    JobAnalysis,
    TailorPreviewResponse,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.jd_analyzer import _keyword_pattern

HUMANIZER_REPLACEMENTS: list[tuple[re.Pattern[str], str, str]] = [
    (re.compile(r"\bspearheaded\b", re.I), "led", "Replaced AI cliché 'spearheaded'"),
    (re.compile(r"\bleveraged\b", re.I), "used", "Replaced AI cliché 'leveraged'"),
    (re.compile(r"\bcutting-edge\b", re.I), "modern", "Replaced AI cliché 'cutting-edge'"),
    (re.compile(r"\brevolutionized\b", re.I), "redesigned", "Replaced AI cliché 'revolutionized'"),
    (re.compile(r"\bsynergized\b", re.I), "aligned", "Replaced AI cliché 'synergized'"),
    (re.compile(r"\bseamlessly\b\s*", re.I), "", "Removed filler 'seamlessly'"),
    (re.compile(r"^responsible for\s+", re.I), "Owned ", "Replaced passive 'responsible for'"),
    (re.compile(r"^worked on\s+", re.I), "Built ", "Replaced weak opener 'worked on'"),
    (re.compile(r"^helped with\s+", re.I), "Contributed to ", "Replaced weak opener 'helped with'"),
]


def _match_case(replacement: str, original_token: str) -> str:
    if not replacement:
        return ""
    if original_token and original_token[0].isupper():
        return replacement[0].upper() + replacement[1:]
    return replacement


def _clean_bullet_humanizer(text: str) -> tuple[str, list[str]]:
    updated = text.strip()
    notes: list[str] = []
    for pattern, repl, note in HUMANIZER_REPLACEMENTS:
        match = pattern.search(updated)
        if match:
            updated = pattern.sub(_match_case(repl, match.group(0)), updated)
            notes.append(note)
    updated = re.sub(r"\s{2,}", " ", updated).strip()
    if updated and updated[0].islower():
        updated = updated[0].upper() + updated[1:]
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
    adapt_location: bool = True,
) -> TailorPreviewResponse:
    """Create a tailored resume preview with explicit location and per-experience comparisons."""
    base_report = score_resume_against_job(
        job_id=job_id,
        resume_id=resume_id,
        resume=base_resume,
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text=raw_resume_text,
    )

    tailored = copy.deepcopy(base_resume)
    field_changes: list[FieldChange] = []

    normalized_job_loc = _normalize_city_state(job.location)
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

    experience_comparisons: list[ExperienceComparison] = []
    for exp in tailored.experience:
        scored_bullets: list[tuple[float, int, BulletComparison]] = []
        for idx, bullet in enumerate(exp.bullets):
            original_text = bullet.text
            cleaned_text, humanizer_notes = _clean_bullet_humanizer(original_text)
            matched_kws = [
                ws.keyword
                for ws in job.weighted_skills
                if _keyword_pattern(ws.keyword).search(cleaned_text)
            ]
            relevance_score = sum(
                ws.weight
                for ws in job.weighted_skills
                if _keyword_pattern(ws.keyword).search(cleaned_text)
            )
            bullet.text = cleaned_text
            if cleaned_text != original_text:
                bullet.provenance = "REFRAMED"

            scored_bullets.append(
                (
                    relevance_score,
                    idx,
                    BulletComparison(
                        bullet_id=bullet.id or f"{exp.id}_b{idx + 1}",
                        original_text=original_text,
                        tailored_text=cleaned_text,
                        status="polished" if cleaned_text != original_text else "unchanged",
                        matched_keywords=matched_kws,
                        notes=humanizer_notes,
                    ),
                )
            )

        # Reorder bullets within each role by relevance to the job's weighted skills
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
        job=job,
        rules=rules,
        settings=settings,
        raw_resume_text="",
    )

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
    )
