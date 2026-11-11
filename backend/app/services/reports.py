"""Cross-session skills gap aggregation and HTML/JSON analytics reporting."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.db.models import (
    JobPostingRecord,
    ResumeRecord,
    ScrapeSessionRecord,
    SeenJobFingerprintRecord,
    TailoringRunRecord,
)
from backend.app.schemas.job import (
    AnalyticsReportResponse,
    JobAnalysis,
    ReportBucketItem,
    RoleGapBreakdown,
    SessionSkillGapItem,
    SessionSkillsGapResponse,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.config_manager import ConfigManager
from backend.app.services.jd_analyzer import _keyword_pattern
from backend.app.services.resume_parser import resume_to_plain_text

_TIER_ORDER = {
    "core_must_have": 4,
    "important_systems": 3,
    "senior_leadership": 2,
    "bonus_nice_to_have": 1,
}


def _to_buckets(counter: Counter[str], total: int, limit: int = 12) -> list[ReportBucketItem]:
    if total <= 0:
        return []
    items: list[ReportBucketItem] = []
    for label, count in counter.most_common(limit):
        items.append(
            ReportBucketItem(
                label=label,
                count=count,
                pct=round((count / total) * 100.0, 1),
            )
        )
    return items


def build_session_skills_gap(
    db: Session,
    config_manager: ConfigManager,
    session_id: int | None = None,
) -> SessionSkillsGapResponse:
    """Aggregate weighted JD skill demand vs. stored base resume coverage across active jobs."""
    session_name = "All Sessions"
    if session_id is not None:
        sess = db.get(ScrapeSessionRecord, session_id)
        if sess is not None:
            session_name = sess.name

    stmt = select(JobPostingRecord).where(JobPostingRecord.disposition != "discarded")
    if session_id is not None:
        stmt = stmt.where(JobPostingRecord.session_id == session_id)
    jobs = list(db.scalars(stmt.order_by(JobPostingRecord.id.desc())).all())

    resumes = list(db.scalars(select(ResumeRecord).order_by(ResumeRecord.is_base.desc(), ResumeRecord.id.desc())).all())
    resume_texts: list[tuple[str, str, str]] = []
    resumes_by_role: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for res in resumes:
        canonical = CanonicalResume.model_validate_json(res.content_json)
        text = f"{resume_to_plain_text(canonical)}\n{res.raw_text or ''}".strip()
        resume_texts.append((res.name, res.role_track, text))
        resumes_by_role[res.role_track].append((res.name, text))

    # Aggregate global skill occurrences (counted at most once per posting)
    skill_meta: dict[str, tuple[str, str, str]] = {}  # norm -> (display_kw, tier, priority_label)
    global_counts: Counter[str] = Counter()
    role_counts: dict[str, Counter[str]] = defaultdict(Counter)
    role_job_totals: Counter[str] = Counter()
    role_relevance_sums: dict[str, list[float]] = defaultdict(list)

    for job in jobs:
        analysis = JobAnalysis.model_validate(json.loads(job.analysis_json))
        role_track = analysis.role_track or job.role_track or "senior_swe"
        role_job_totals[role_track] += 1
        role_relevance_sums[role_track].append(float(job.relevance_score or 0.0))

        seen_in_job: set[str] = set()
        for sk in analysis.weighted_skills:
            norm = sk.keyword.strip().lower()
            if not norm or norm in seen_in_job:
                continue
            seen_in_job.add(norm)
            if norm not in skill_meta:
                skill_meta[norm] = (sk.keyword, sk.tier, sk.priority_label)
            global_counts[norm] += 1
            role_counts[role_track][norm] += 1

    total_jobs = len(jobs)
    coverage_cache: dict[str, list[str]] = {}

    def _covered_names(norm_kw: str, role_filter: str | None = None) -> list[str]:
        display_kw = skill_meta[norm_kw][0]
        pat = _keyword_pattern(display_kw)
        if role_filter is None:
            if norm_kw not in coverage_cache:
                coverage_cache[norm_kw] = [name for name, _, txt in resume_texts if pat.search(txt)]
            return coverage_cache[norm_kw]
        role_res = resumes_by_role.get(role_filter, [])
        if role_res:
            return [name for name, txt in role_res if pat.search(txt)]
        return [name for name, _, txt in resume_texts if pat.search(txt)]

    def _build_item(norm_kw: str, count: int, denom: int, role_filter: str | None = None) -> SessionSkillGapItem:
        display_kw, tier, prio = skill_meta[norm_kw]
        covered_by = _covered_names(norm_kw, role_filter)
        return SessionSkillGapItem(
            keyword=display_kw,
            tier=tier,
            priority_label=prio,
            demand_count=count,
            demand_pct=round((count / max(1, denom)) * 100.0, 1),
            covered_by_resumes=covered_by,
            is_covered=bool(covered_by),
        )

    all_global_items = [
        _build_item(norm_kw, cnt, total_jobs)
        for norm_kw, cnt in global_counts.items()
    ]
    all_global_items.sort(
        key=lambda item: (-item.demand_count, -_TIER_ORDER.get(item.tier, 0), item.keyword.lower())
    )

    overall_missing = [it for it in all_global_items if not it.is_covered]
    overall_strengths = [it for it in all_global_items if it.is_covered]

    by_role: list[RoleGapBreakdown] = []
    for role_track, r_total in sorted(role_job_totals.items(), key=lambda x: -x[1]):
        r_items = [
            _build_item(norm_kw, cnt, r_total, role_filter=role_track)
            for norm_kw, cnt in role_counts[role_track].items()
        ]
        r_items.sort(
            key=lambda item: (-item.demand_count, -_TIER_ORDER.get(item.tier, 0), item.keyword.lower())
        )
        scores = role_relevance_sums[role_track]
        avg_rel = round(sum(scores) / len(scores), 1) if scores else 0.0
        by_role.append(
            RoleGapBreakdown(
                role_track=role_track,
                job_count=r_total,
                has_base_resume=bool(resumes_by_role.get(role_track)),
                avg_relevance=avg_rel,
                top_missing_skills=[it for it in r_items if not it.is_covered][:10],
                top_matched_skills=[it for it in r_items if it.is_covered][:10],
            )
        )

    return SessionSkillsGapResponse(
        session_id=session_id,
        session_name=session_name,
        total_active_jobs=total_jobs,
        covered_skill_count=len(overall_strengths),
        missing_skill_count=len(overall_missing),
        overall_missing=overall_missing[:25],
        overall_strengths=overall_strengths[:25],
        by_role=by_role,
    )


def render_html_dashboard(summary: AnalyticsReportResponse) -> str:
    """Render a self-contained dark-mode HTML metrics report matching the UI visual theme."""

    def _render_bars(title: str, items: list[ReportBucketItem], accent: str = "#0a84ff") -> str:
        if not items:
            return f"""
            <div class="card">
              <h3>{escape(title)}</h3>
              <p class="muted">No records yet.</p>
            </div>"""
        rows = []
        max_count = max(item.count for item in items) or 1
        for item in items:
            width = max(4, int(round((item.count / max_count) * 100)))
            rows.append(
                f"""
              <div class="bar-row">
                <div class="bar-meta">
                  <span>{escape(item.label)}</span>
                  <span class="mono">{item.count} ({item.pct}%)</span>
                </div>
                <div class="bar-track">
                  <div class="bar-fill" style="width:{width}%;background:{accent};"></div>
                </div>
              </div>"""
            )
        return f"""
        <div class="card">
          <h3>{escape(title)}</h3>
          <div class="bar-list">{''.join(rows)}</div>
        </div>"""

    missing_rows = "".join(
        f"""
        <tr>
          <td>{escape(sk.keyword)}</td>
          <td><span class="pill">{escape(sk.priority_label)}</span></td>
          <td class="mono">{sk.demand_count} ({sk.demand_pct}%)</td>
        </tr>"""
        for sk in summary.top_missing_skills[:12]
    ) or '<tr><td colspan="3" class="muted">All tracked JD skills are covered by your base resumes.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>CareerFlow — Analytics Report</title>
<style>
  :root {{
    color-scheme: dark;
    --bg: #0b0f1a;
    --card: #131a2a;
    --border: rgba(255,255,255,0.09);
    --text: #f3f6fc;
    --muted: #9aa7bd;
    --blue: #0a84ff;
    --green: #30d158;
    --amber: #ff9f0a;
    --red: #ff453a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Inter", sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.5;
  }}
  .wrap {{ max-width: 1180px; margin: 0 auto; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }}
  h1 {{ margin: 0; font-size: 24px; font-weight: 700; letter-spacing: -0.02em; }}
  h3 {{ margin: 0 0 14px; font-size: 14px; font-weight: 600; color: #dbe4f3; text-transform: uppercase; letter-spacing: 0.04em; }}
  .muted {{ color: var(--muted); font-size: 13px; }}
  .mono {{ font-variant-numeric: tabular-nums; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); }}
  .kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 14px; margin-bottom: 22px; }}
  .kpi {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px 18px; }}
  .kpi-val {{ font-size: 28px; font-weight: 700; margin-top: 4px; letter-spacing: -0.02em; }}
  .kpi-lbl {{ font-size: 12px; color: var(--muted); }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px; margin-bottom: 22px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 18px 20px; }}
  .bar-list {{ display: flex; flex-direction: column; gap: 10px; }}
  .bar-meta {{ display: flex; justify-content: space-between; font-size: 13px; margin-bottom: 4px; }}
  .bar-track {{ height: 8px; border-radius: 999px; background: rgba(255,255,255,0.06); overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 999px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ text-align: left; padding: 9px 10px; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--muted); font-weight: 600; font-size: 12px; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 11px; background: rgba(10,132,255,0.16); color: #7cc0ff; border: 1px solid rgba(10,132,255,0.3); }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>CareerFlow — Analytics Report</h1>
      <div class="muted">Scope: {escape(summary.session_name)} &middot; Generated {summary.generated_at.strftime('%Y-%m-%d %H:%M UTC')}</div>
    </div>
    <div class="mono">Permanent Seen Ledger: {summary.seen_ledger_count} unique jobs</div>
  </header>

  <section class="kpis">
    <div class="kpi"><div class="kpi-lbl">Total Scanned</div><div class="kpi-val">{summary.total_scanned}</div></div>
    <div class="kpi"><div class="kpi-lbl">Saved Active Jobs</div><div class="kpi-val" style="color:var(--green)">{summary.total_saved}</div></div>
    <div class="kpi"><div class="kpi-lbl">Auto-Filtered Inline</div><div class="kpi-val" style="color:var(--amber)">{summary.total_filtered}</div></div>
    <div class="kpi"><div class="kpi-lbl">Manually Discarded</div><div class="kpi-val" style="color:var(--red)">{summary.total_discarded}</div></div>
    <div class="kpi"><div class="kpi-lbl">Kept Without Salary</div><div class="kpi-val">{summary.omitted_salary_count}</div></div>
    <div class="kpi"><div class="kpi-lbl">Avg Relevance / Exports</div><div class="kpi-val" style="color:var(--blue)">{summary.avg_relevance_score}% &middot; {summary.total_exports}</div></div>
  </section>

  <section class="grid">
    {_render_bars("Jobs by Location", summary.by_location, "#0a84ff")}
    {_render_bars("Jobs by Target Role", summary.by_role, "#30d158")}
    {_render_bars("Application Pipeline Status", summary.by_status, "#64d2ff")}
    {_render_bars("Inline Filter Drops", summary.by_filter_reason, "#ff9f0a")}
    {_render_bars("Job Sources", summary.by_source, "#bf5af2")}
    {_render_bars("Detected Compensation Currency", summary.by_currency, "#32d74b")}
  </section>

  <section class="card">
    <h3>Top Missing Skills Across Active Jobs</h3>
    <table>
      <thead><tr><th>Skill</th><th>Priority</th><th>Job Demand</th></tr></thead>
      <tbody>{missing_rows}</tbody>
    </table>
  </section>
</div>
</body>
</html>"""


def build_analytics_summary(
    db: Session,
    config_manager: ConfigManager,
    session_id: int | None = None,
    write_html: bool = True,
    output_dir: Path | None = None,
) -> tuple[AnalyticsReportResponse, str]:
    """Build session/global analytics report metrics and write standalone HTML dashboard."""
    settings = config_manager.get_settings()
    sess_stmt = select(ScrapeSessionRecord)
    if session_id is not None:
        sess_stmt = sess_stmt.where(ScrapeSessionRecord.id == session_id)
    sessions = list(db.scalars(sess_stmt).all())

    total_sessions = len(list(db.scalars(select(ScrapeSessionRecord)).all()))
    session_name = sessions[0].name if (session_id is not None and sessions) else "All Sessions"

    job_stmt = select(JobPostingRecord)
    if session_id is not None:
        job_stmt = job_stmt.where(JobPostingRecord.session_id == session_id)
    jobs = list(db.scalars(job_stmt).all())

    active_jobs = [j for j in jobs if j.disposition != "discarded"]
    discarded_jobs = [j for j in jobs if j.disposition == "discarded"]

    scanned_from_sessions = sum(int(s.scanned_count or 0) for s in sessions)
    filtered_from_sessions = sum(int(s.filtered_count or 0) for s in sessions)
    total_scanned = max(scanned_from_sessions, len(jobs) + filtered_from_sessions)

    loc_counter: Counter[str] = Counter()
    role_counter: Counter[str] = Counter()
    source_counter: Counter[str] = Counter()
    currency_counter: Counter[str] = Counter()
    status_counter: Counter[str] = Counter()
    filter_counter: Counter[str] = Counter()

    omitted_salary = 0
    rel_scores: list[float] = []

    for j in active_jobs:
        loc_counter[j.location or "Unspecified"] += 1
        role_counter[j.role_track or "senior_swe"] += 1
        source_counter[(j.source or "manual").split(":")[0]] += 1
        status_counter[j.application_status or "ready"] += 1
        rel_scores.append(float(j.relevance_score or 0.0))
        if j.salary_min is None:
            omitted_salary += 1
            currency_counter["Omitted"] += 1
        else:
            currency_counter[j.salary_currency or "USD"] += 1

    for _ in discarded_jobs:
        status_counter["discarded"] += 1

    for s in sessions:
        breakdown = json.loads(s.filter_breakdown_json or "{}")
        for reason, cnt in breakdown.items():
            filter_counter[reason] += int(cnt)

    seen_ledger_count = int(db.scalar(select(func.count(SeenJobFingerprintRecord.id))) or 0)

    exp_stmt = select(func.count(TailoringRunRecord.id))
    if session_id is not None and jobs:
        job_ids = [j.id for j in jobs]
        exp_stmt = exp_stmt.where(TailoringRunRecord.job_id.in_(job_ids))
    elif session_id is not None:
        exp_stmt = None
    total_exports = int(db.scalar(exp_stmt) or 0) if exp_stmt is not None else 0

    gap = build_session_skills_gap(db, config_manager, session_id=session_id)
    avg_rel = round(sum(rel_scores) / len(rel_scores), 1) if rel_scores else 0.0

    filter_total = sum(filter_counter.values())
    total_all_jobs = len(jobs)
    summary = AnalyticsReportResponse(
        generated_at=datetime.now(timezone.utc),
        session_id=session_id,
        session_name=session_name,
        total_sessions=total_sessions,
        total_scanned=total_scanned,
        total_saved=len(active_jobs),
        total_filtered=filtered_from_sessions,
        total_discarded=len(discarded_jobs),
        seen_ledger_count=seen_ledger_count,
        omitted_salary_count=omitted_salary,
        avg_relevance_score=avg_rel,
        total_exports=total_exports,
        by_location=_to_buckets(loc_counter, len(active_jobs)),
        by_role=_to_buckets(role_counter, len(active_jobs)),
        by_source=_to_buckets(source_counter, len(active_jobs)),
        by_currency=_to_buckets(currency_counter, len(active_jobs)),
        by_status=_to_buckets(status_counter, total_all_jobs),
        by_filter_reason=_to_buckets(filter_counter, filter_total),
        top_missing_skills=gap.overall_missing[:12],
        html_report_path=None,
    )

    html = render_html_dashboard(summary)
    if write_html:
        out_dir = output_dir or Path(settings.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        html_path = out_dir / "dashboard.html"
        html_path.write_text(html, encoding="utf-8")
        summary.html_report_path = str(html_path.as_posix())

    return summary, html
