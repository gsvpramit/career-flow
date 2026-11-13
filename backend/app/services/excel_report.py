"""Multi-sheet Excel (.xlsx) workbook generator for sessions, applied standing, and skills reports."""

from __future__ import annotations

import io
import json
from collections import defaultdict
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    JobPostingRecord,
    ScrapeSessionRecord,
    SessionFilteredJobRecord,
    TailoringRunRecord,
)
from backend.app.schemas.job import JobAnalysis
from backend.app.services.config_manager import ConfigManager
from backend.app.services.label_formatter import (
    format_filter_reason_label,
    format_role_track_label,
    format_source_label,
    format_status_label,
)
from backend.app.services.reports import build_analytics_summary, build_session_skills_gap
from backend.app.services.skills_graph import classify_job_domain
from backend.app.services.timezone_utils import to_eastern

_HEADER_FILL = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
_HEADER_FONT = Font(color="F8FAFC", bold=True, size=11)
_SECTION_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
_SECTION_FONT = Font(color="FFFFFF", bold=True, size=12)
_ZEBRA_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
_THIN_BORDER = Border(
    left=Side(style="thin", color="CBD5E1"),
    right=Side(style="thin", color="CBD5E1"),
    top=Side(style="thin", color="CBD5E1"),
    bottom=Side(style="thin", color="CBD5E1"),
)


_LINK_FONT = Font(name="Segoe UI", size=10, color="0000EE", underline="single")


def _style_table_sheet(ws, headers: list[str], rows: list[list[object]]) -> None:
    ws.append(headers)
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        cell.border = _THIN_BORDER
    ws.row_dimensions[1].height = 24

    for r_idx, row_vals in enumerate(rows, start=2):
        ws.append(row_vals)
        is_even = r_idx % 2 == 0
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=r_idx, column=col_idx)
            if is_even:
                cell.fill = _ZEBRA_FILL
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = _THIN_BORDER

            # Auto-format URLs as clickable Excel hyperlinks with clean label
            val = row_vals[col_idx - 1]
            header = headers[col_idx - 1].lower()
            if isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                cell.value = "Apply / Open Posting"
                cell.hyperlink = val
                cell.font = _LINK_FONT

    ws.freeze_panes = "A2"
    if rows:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{len(rows) + 1}"

    for col_idx, header in enumerate(headers, start=1):
        max_len = len(str(header))
        for r in rows[:200]:
            if col_idx - 1 < len(r) and r[col_idx - 1] is not None:
                raw_lines = str(r[col_idx - 1]).splitlines()
                val_str = raw_lines[0] if raw_lines else ""
                max_len = max(max_len, min(52, len(val_str)))
        ws.column_dimensions[get_column_letter(col_idx)].width = max(12, min(54, max_len + 4))


def _fmt_dt(dt) -> str:
    eastern = to_eastern(dt)
    if eastern is None:
        return ""
    return eastern.strftime("%Y-%m-%d %I:%M %p ET")


def build_sessions_excel_workbook(
    db: Session,
    config_manager: ConfigManager,
    session_id: int | None = None,
) -> bytes:
    """Build a multi-sheet styled Excel (.xlsx) report covering sessions, jobs, applied tracking, and skills."""
    wb = Workbook()

    summary, _ = build_analytics_summary(
        db=db,
        config_manager=config_manager,
        session_id=session_id,
        write_html=False,
    )

    sess_stmt = select(ScrapeSessionRecord).order_by(ScrapeSessionRecord.id.desc())
    if session_id is not None:
        sess_stmt = sess_stmt.where(ScrapeSessionRecord.id == session_id)
    sessions = list(db.scalars(sess_stmt).all())
    session_names = {s.id: s.name for s in sessions}

    job_stmt = select(JobPostingRecord).order_by(JobPostingRecord.id.desc())
    if session_id is not None:
        job_stmt = job_stmt.where(JobPostingRecord.session_id == session_id)
    jobs = list(db.scalars(job_stmt).all())

    runs = list(db.scalars(select(TailoringRunRecord).order_by(TailoringRunRecord.id.desc())).all())
    latest_run_by_job: dict[int, TailoringRunRecord] = {}
    for run in runs:
        if run.job_id not in latest_run_by_job:
            latest_run_by_job[run.job_id] = run

    jobs_by_session: dict[int, list[JobPostingRecord]] = defaultdict(list)
    for j in jobs:
        if j.session_id is not None:
            jobs_by_session[j.session_id].append(j)

    # Sheet 2: Overview & Sessions KPI Summary
    ws_overview = wb.create_sheet("Overview & Analytics")
    kpi_rows: list[list[object]] = [
        ["Scope", summary.session_name],
        ["Generated At", _fmt_dt(summary.generated_at)],
        ["Total Sessions", summary.total_sessions],
        ["Total Scanned", summary.total_scanned],
        ["Saved Active Jobs", summary.total_saved],
        ["Auto-Filtered Inline", summary.total_filtered],
        ["Manually Discarded", summary.total_discarded],
        ["Jobs Applied / Active Funnel", summary.total_applied],
        ["Interviewing + Offers", f"{summary.interviewing_count} / {summary.offer_count}"],
        ["Resume Exports Created", summary.total_exports],
        ["Avg Base Relevance (%)", summary.avg_relevance_score],
        ["Avg Tailored ATS (%)", summary.avg_tailored_score],
        ["Avg ATS Lift (+%)", summary.avg_ats_lift],
    ]
    ws_overview.append(["CareerFlow Analytics Summary", "Value"])
    for c_i in (1, 2):
        cell = ws_overview.cell(row=1, column=c_i)
        cell.fill = _SECTION_FILL
        cell.font = _SECTION_FONT
    for label, val in kpi_rows:
        ws_overview.append([label, val])

    ws_overview.append([])
    sess_header_row = ws_overview.max_row + 1
    sess_headers = [
        "Session ID",
        "Session Name",
        "Posted Window",
        "Scanned",
        "Saved Active",
        "Filtered Inline",
        "Discarded",
        "Applied / Active",
        "Exports",
        "Created (ET)",
    ]
    ws_overview.append(sess_headers)
    for col_idx in range(1, len(sess_headers) + 1):
        c = ws_overview.cell(row=sess_header_row, column=col_idx)
        c.fill = _HEADER_FILL
        c.font = _HEADER_FONT
        c.border = _THIN_BORDER

    for s in sessions:
        s_jobs = jobs_by_session.get(s.id, [])
        active = [j for j in s_jobs if j.disposition != "discarded"]
        discarded = [j for j in s_jobs if j.disposition == "discarded"]
        applied_cnt = sum(
            1 for j in active if j.application_status in ("applied", "screening", "interviewing", "offer", "rejected")
        )
        export_cnt = sum(1 for j in active if j.id in latest_run_by_job)
        ws_overview.append(
            [
                s.id,
                s.name,
                s.posted_within,
                int(s.scanned_count or 0),
                len(active),
                int(s.filtered_count or 0),
                len(discarded),
                applied_cnt,
                export_cnt,
                _fmt_dt(s.created_at),
            ]
        )

    ws_overview.column_dimensions["A"].width = 30
    ws_overview.column_dimensions["B"].width = 36
    for idx in range(3, len(sess_headers) + 1):
        ws_overview.column_dimensions[get_column_letter(idx)].width = 18

    # Sheet 1 (Primary Active): Jobs & Direct Apply Links
    ws_jobs = wb.active
    ws_jobs.title = "Jobs & Apply Links"
    job_headers = [
        "Job ID",
        "Session",
        "Company",
        "Role Title",
        "Domain",
        "Role Track",
        "Location",
        "Work Mode",
        "Job Type",
        "Comp Min",
        "Comp Max",
        "Currency",
        "YoE",
        "Base Score %",
        "Tailored ATS %",
        "Disposition",
        "Status",
        "Applied At",
        "Notes",
        "Top Skills Demanded",
        "Posted At",
        "Source",
        "Apply Link",
    ]
    job_rows: list[list[object]] = []
    for j in jobs:
        analysis = JobAnalysis.model_validate_json(j.analysis_json)
        domain = classify_job_domain(j.role_track, j.title, j.raw_text)
        run = latest_run_by_job.get(j.id)
        yoe_str = ""
        if analysis.yoe.min_years is not None:
            yoe_str = (
                f"{analysis.yoe.min_years}-{analysis.yoe.max_years}y"
                if analysis.yoe.max_years is not None
                else f"{analysis.yoe.min_years}+y"
            )
        skills_str = ", ".join(ws.keyword for ws in (analysis.weighted_skills or [])[:10])
        job_rows.append(
            [
                j.id,
                session_names.get(j.session_id or -1, f"Session {j.session_id or ''}"),
                j.company,
                j.title,
                domain,
                format_role_track_label(j.role_track or "senior_swe", config_manager),
                j.location or "Unspecified",
                j.work_type,
                j.job_type,
                j.salary_min or "",
                j.salary_max or "",
                j.salary_currency or "",
                yoe_str,
                round(float(run.base_score if run else j.relevance_score or 0.0), 1),
                round(float(run.tailored_score), 1) if run else "",
                j.disposition,
                format_status_label(j.application_status or "ready"),
                _fmt_dt(j.applied_at),
                j.application_notes or "",
                skills_str,
                _fmt_dt(j.posted_at),
                format_source_label(j.source or "manual"),
                j.url or "",
            ]
        )
    _style_table_sheet(ws_jobs, job_headers, job_rows)

    # Sheet 3: Applied Standing
    ws_applied = wb.create_sheet("Applied Standing")
    applied_headers = [
        "Job ID",
        "Session",
        "Company",
        "Role Title",
        "Location",
        "Role Track",
        "Standing",
        "Applied At",
        "Base ATS %",
        "Tailored ATS %",
        "Generated Resume Files",
        "Application Notes",
        "Posting URL",
    ]
    applied_rows: list[list[object]] = [
        [
            item.job_id,
            item.session_name,
            item.company,
            item.title,
            item.location,
            item.role_label,
            item.status_label,
            _fmt_dt(item.applied_at),
            item.base_score if item.base_score is not None else "",
            item.tailored_score if item.tailored_score is not None else "",
            ", ".join(item.latest_files),
            item.application_notes,
            item.url or "",
        ]
        for item in summary.applied_jobs
    ]
    _style_table_sheet(ws_applied, applied_headers, applied_rows)

    # Sheet 4: Filtered & Seen Log
    ws_filtered = wb.create_sheet("Filtered & Seen Log")
    filt_stmt = select(SessionFilteredJobRecord).order_by(SessionFilteredJobRecord.id.desc())
    if session_id is not None:
        filt_stmt = filt_stmt.where(SessionFilteredJobRecord.session_id == session_id)
    filt_rows_db = list(db.scalars(filt_stmt).all())
    filt_headers = [
        "Session",
        "Category",
        "Company",
        "Role Title",
        "Location",
        "Role Track",
        "Primary Filter Reason",
        "All Reasons",
        "Source",
        "Posted At",
        "URL",
    ]
    filt_rows: list[list[object]] = []
    for f in filt_rows_db:
        reason_codes = json.loads(f.filter_reasons_json or "[]") or [f.filter_reason]
        filt_rows.append(
            [
                session_names.get(f.session_id, f"Session {f.session_id}"),
                "Auto-Filtered" if f.category == "auto_filtered" else "Seen / Skipped",
                f.company,
                f.title,
                f.location or "Unspecified",
                format_role_track_label(f.role_track or "senior_swe", config_manager),
                format_filter_reason_label(f.filter_reason),
                ", ".join(format_filter_reason_label(str(c)) for c in reason_codes),
                format_source_label(f.source or "manual"),
                _fmt_dt(f.posted_at),
                f.url or "",
            ]
        )
    _style_table_sheet(ws_filtered, filt_headers, filt_rows)

    # Sheet 5: Skills Demand
    ws_skills = wb.create_sheet("Skills Demand")
    gap = build_session_skills_gap(db=db, config_manager=config_manager, session_id=session_id)
    combined_skills = sorted(
        [*gap.overall_missing, *gap.overall_strengths],
        key=lambda x: (-x.demand_count, x.is_covered, x.keyword.lower()),
    )
    skill_headers = [
        "Skill Keyword",
        "Priority Tier",
        "Job Count",
        "Demand %",
        "Base Resume Coverage",
        "Covering Resumes",
    ]
    skill_rows: list[list[object]] = [
        [
            sk.keyword,
            sk.priority_label,
            sk.demand_count,
            sk.demand_pct,
            "Covered" if sk.is_covered else "Missing",
            ", ".join(sk.covered_by_resumes),
        ]
        for sk in combined_skills
    ]
    _style_table_sheet(ws_skills, skill_headers, skill_rows)

    wb.active = ws_jobs
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
