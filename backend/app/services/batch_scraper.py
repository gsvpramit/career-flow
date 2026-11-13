"""Automated multi-source job scraper with simultaneous inline filtering and permanent deduplication."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db.models import (
    JobPostingRecord,
    ResumeRecord,
    ScrapeSessionRecord,
    SeenJobFingerprintRecord,
    SessionFilteredJobRecord,
    TailoringRunRecord,
)
from backend.app.schemas.config import AppSettings, RoleTrackConfig
from backend.app.schemas.job import (
    FilteredJobSample,
    JobAnalysis,
    JobPostingResponse,
    ScrapeBatchRequest,
    ScrapeBatchResult,
    ScrapeProgressResponse,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.config_manager import ConfigManager
from backend.app.services.jd_analyzer import _keyword_pattern, analyze_job_posting
from backend.app.services.locations import is_us_or_remote_location, matches_target_location
from backend.app.services.scraper import DEFAULT_HEADERS, _clean_html_fragment, fetch_job_posting
from backend.app.services.timezone_utils import to_eastern

FRESHNESS_SECONDS: dict[str, int | None] = {
    "1h": 3600,
    "12h": 43200,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
    "any": None,
}

LINKEDIN_FTPR: dict[str, str] = {
    "1h": "r3600",
    "12h": "r43200",
    "24h": "r86400",
    "7d": "r604800",
    "30d": "r2592000",
}

_TRACKING_QUERY_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "ref",
    "refid",
    "trackingid",
    "trk",
    "trkinfo",
    "currentjobid",
    "position",
    "pagenum",
    "gh_src",
    "lever-source",
    "source",
    "ref_src",
}

FILTER_REASON_LABELS: dict[str, str] = {
    "stale_outside_window": "Outside Time Window",
    "blocked_title": "Blocked Title Keyword",
    "role_mismatch": "Role Track Mismatch",
    "location_mismatch": "Location Mismatch",
    "fetch_failed": "Detail Fetch Failed",
    "empty_jd": "Empty Job Description",
    "no_h1b_sponsorship": "No H-1B Sponsorship",
    "below_min_salary": "Below Min Salary",
    "below_min_hourly": "Below Min Hourly Rate",
    "yoe_too_high": "Experience Above Max",
    "yoe_too_low": "Experience Below Min",
    "below_min_relevance": "Below Min Match Score",
    "duplicate_in_batch": "Duplicate in Batch",
    "already_seen": "Already Seen Previously",
    "seen:saved": "Already Saved in Earlier Run",
    "seen:discarded": "Previously Discarded",
    "seen:auto_filtered": "Previously Filtered by Rules",
}


def format_filter_reason_label(reason: str) -> str:
    """Convert an internal filter/skip code into a readable UI badge label."""
    if reason in FILTER_REASON_LABELS:
        return FILTER_REASON_LABELS[reason]
    if reason.startswith("work_type:"):
        return f"Excluded Work Type ({reason.split(':', 1)[1]})"
    if reason.startswith("job_type:"):
        return f"Excluded Job Type ({reason.split(':', 1)[1]})"
    if reason.startswith("seen:"):
        return f"Already Seen ({reason.split(':', 1)[1]})"
    return reason.replace("_", " ").title()


def _sleep_or_cancel(delay: float, cancel_event: threading.Event | None) -> bool:
    """Sleep for `delay` seconds, returning True immediately if cancellation is signaled."""
    if cancel_event is None:
        time.sleep(delay)
        return False
    return cancel_event.wait(delay)


@dataclass
class RawCandidate:
    """Normalized lightweight card/posting returned by a board scraper before filtering."""

    source: str
    title: str
    company: str
    location: str
    url: str | None
    posted_at: datetime | None = None
    raw_text: str | None = None
    detail_url: str | None = None
    work_type_hint: str | None = None


def canonicalize_url(url: str | None) -> str | None:
    """Strip tracking parameters and trailing slashes for deterministic URL deduplication."""
    if not url or not url.strip():
        return None
    parsed = urlparse(url.strip())
    clean_params = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=False)
        if k.lower() not in _TRACKING_QUERY_PARAMS and not k.lower().startswith("utm_")
    ]
    path = parsed.path.rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            path,
            "",
            urlencode(sorted(clean_params)),
            "",
        )
    )


def hash_url(url: str | None) -> str | None:
    """Return SHA-256 hex digest of a canonicalized job URL."""
    canon = canonicalize_url(url)
    if not canon:
        return None
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _norm_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def make_content_fingerprint(company: str, title: str, location: str) -> str:
    """Create stable hash of normalized company + title + location across reposts/boards."""
    # Collapse city suffixes like "Seattle, WA" vs "Seattle, WA, United States" onto first 2 segments
    loc_parts = [p.strip() for p in (location or "").split(",") if p.strip()]
    loc_core = ", ".join(loc_parts[:2]) if loc_parts else ""
    payload = f"{_norm_token(company)}|{_norm_token(title)}|{_norm_token(loc_core)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_posted_at(raw_dt: Any, now: datetime | None = None) -> datetime | None:
    """Parse ISO timestamps, epoch milliseconds, or relative strings into UTC datetime."""
    ref_now = now or datetime.now(timezone.utc)
    if raw_dt is None or raw_dt == "":
        return None
    if isinstance(raw_dt, datetime):
        return raw_dt if raw_dt.tzinfo else raw_dt.replace(tzinfo=timezone.utc)
    if isinstance(raw_dt, (int, float)):
        ts = float(raw_dt)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            return None

    text = str(raw_dt).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_posted_at(int(text), ref_now)

    try:
        iso_norm = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(iso_norm)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    lower = text.lower()
    if "just now" in lower or "moments ago" in lower:
        return ref_now
    rel = re.search(r"(\d+)\s*(minute|min|hour|hr|day|week|month)s?\s*ago", lower)
    if rel:
        qty = int(rel.group(1))
        unit = rel.group(2)
        if unit.startswith("min"):
            return ref_now - timedelta(minutes=qty)
        if unit.startswith("h"):
            return ref_now - timedelta(hours=qty)
        if unit.startswith("day"):
            return ref_now - timedelta(days=qty)
        if unit.startswith("week"):
            return ref_now - timedelta(weeks=qty)
        if unit.startswith("month"):
            return ref_now - timedelta(days=qty * 30)
    return None


def is_within_freshness(
    posted_at: datetime | None,
    posted_within: str,
    now: datetime | None = None,
) -> bool:
    """Return False only when an explicit timestamp is older than the requested window."""
    limit_seconds = FRESHNESS_SECONDS.get(posted_within, None)
    if limit_seconds is None or posted_at is None:
        return True
    ref_now = now or datetime.now(timezone.utc)
    aware_dt = posted_at if posted_at.tzinfo else posted_at.replace(tzinfo=timezone.utc)
    age = (ref_now - aware_dt).total_seconds()
    return age <= limit_seconds


def is_job_already_seen(
    db: Session,
    url_hash: str | None,
    content_fingerprint: str,
    source: str | None = None,
) -> tuple[bool, str | None]:
    """Check permanent seen ledger and existing job_postings so saved/discarded jobs never return."""
    if url_hash:
        seen_url = db.scalars(
            select(SeenJobFingerprintRecord).where(SeenJobFingerprintRecord.url_hash == url_hash)
        ).first()
        if seen_url is not None:
            return True, f"seen:{seen_url.disposition}"

        job_url = db.scalars(
            select(JobPostingRecord).where(JobPostingRecord.url_hash == url_hash)
        ).first()
        if job_url is not None:
            return True, f"seen:{job_url.disposition}"

    seen_fp = db.scalars(
        select(SeenJobFingerprintRecord).where(
            SeenJobFingerprintRecord.content_fingerprint == content_fingerprint
        )
    ).all()
    for row in seen_fp:
        # Distinct URLs on the exact same ATS board represent separate req IDs; different sources are reposts
        if url_hash and row.url_hash and row.url_hash != url_hash and source and row.source == source:
            continue
        return True, f"seen:{row.disposition}"

    job_fp = db.scalars(
        select(JobPostingRecord).where(JobPostingRecord.content_fingerprint == content_fingerprint)
    ).all()
    for row in job_fp:
        if url_hash and row.url_hash and row.url_hash != url_hash and source and row.source == source:
            continue
        return True, f"seen:{row.disposition}"

    return False, None


def record_seen_job(
    db: Session,
    *,
    url: str | None,
    url_hash: str | None,
    content_fingerprint: str,
    company: str,
    title: str,
    location: str,
    source: str,
    disposition: str,
    filter_reason: str | None = None,
    session_id: int | None = None,
) -> None:
    """Upsert permanent deduplication record for saved, discarded, or auto-filtered postings."""
    record = None
    if url_hash:
        record = db.scalars(
            select(SeenJobFingerprintRecord).where(SeenJobFingerprintRecord.url_hash == url_hash)
        ).first()
    if record is None:
        candidates = db.scalars(
            select(SeenJobFingerprintRecord).where(
                SeenJobFingerprintRecord.content_fingerprint == content_fingerprint
            )
        ).all()
        for cand in candidates:
            if not (url_hash and cand.url_hash and cand.url_hash != url_hash and cand.source == source):
                record = cand
                break
    now = datetime.now(timezone.utc)
    if record is None:
        db.add(
            SeenJobFingerprintRecord(
                url_hash=url_hash,
                content_fingerprint=content_fingerprint,
                company=company[:200],
                title=title[:255],
                location=location[:200],
                source=source[:60],
                source_url=url[:1000] if url else None,
                disposition=disposition,
                filter_reason=filter_reason[:255] if filter_reason else None,
                first_session_id=session_id,
                first_seen_at=now,
                updated_at=now,
            )
        )
    else:
        record.disposition = disposition
        record.filter_reason = filter_reason[:255] if filter_reason else record.filter_reason
        if url_hash and not record.url_hash:
            record.url_hash = url_hash
        record.updated_at = now


_ROLE_NOUNS = {
    "engineer",
    "developer",
    "architect",
    "sde",
    "fde",
    "scientist",
    "mts",
    "sre",
    "swe",
    "mle",
    "analyst",
    "specialist",
}

_MID_EXCLUDED_LEVEL_WORDS = (
    "intern",
    "internship",
    "co-op",
    "coop",
    "junior",
    "jr",
    "entry level",
    "new grad",
    "university graduate",
    "associate",
    "senior",
    "staff",
    "principal",
    "distinguished",
    "fellow",
    "manager",
    "director",
    "vp",
    "vice president",
    "chief",
    "lead",
    "head of",
    "founding",
)


def _match_target_role(
    title: str,
    selected_tracks: list[RoleTrackConfig],
) -> RoleTrackConfig | None:
    """Match a posting title against selected role tracks via word-bounded aliases."""
    if not selected_tracks:
        return None
    norm_title = re.sub(r"[/\-–]+", " ", title.lower())
    norm_title = re.sub(r"\bsr\.?\b", "senior", norm_title)
    norm_title = re.sub(r"\bjr\.?\b", "junior", norm_title)
    lower = f" {norm_title} "
    title_tokens = set(re.findall(r"[a-z0-9]+", lower))
    has_role_noun = bool(title_tokens & _ROLE_NOUNS)
    best_track: RoleTrackConfig | None = None
    best_score = 0

    for track in selected_tracks:
        clean_display = re.sub(r"\([^)]*\)", "", track.display_name).strip()
        candidates = [track.display_name, clean_display, *track.aliases]
        for alias in candidates:
            norm_alias = re.sub(r"[/\-–]+", " ", alias.strip().lower())
            if not norm_alias:
                continue
            # Prevent un-leveled catch-all aliases ("software engineer", "member of technical staff")
            # on mid_swe from matching explicitly Senior/Staff/Principal/Junior/Manager titles.
            if track.id == "mid_swe" and norm_alias in (
                "software engineer",
                "application engineer",
                "member of technical staff",
            ):
                if any(
                    re.search(rf"(?<![a-z0-9]){re.escape(lvl)}(?![a-z0-9])", lower)
                    for lvl in _MID_EXCLUDED_LEVEL_WORDS
                ):
                    continue
                if re.search(r"\b(?:swe|sde|software engineer)\s*(?:1|i|3|iii)\b", lower):
                    continue
            if re.search(rf"(?<![a-z0-9]){re.escape(norm_alias)}(?![a-z0-9])", lower):
                score = len(norm_alias) + 10
                if score > best_score:
                    best_score = score
                    best_track = track
            elif has_role_noun:
                # Multi-word distinctive token fallback (requires >=2 non-generic words + role noun)
                alias_tokens = [tok for tok in re.findall(r"[a-z0-9]+", norm_alias) if len(tok) > 2]
                generic_skip = {
                    "senior",
                    "staff",
                    "lead",
                    "principal",
                    "engineer",
                    "developer",
                    "level",
                    "software",
                }
                distinctive = [tok for tok in alias_tokens if tok not in generic_skip]
                if len(distinctive) >= 2 and all(tok in title_tokens for tok in distinctive):
                    score = sum(len(t) for t in distinctive)
                    if score > best_score:
                        best_score = score
                        best_track = track

    return best_track


def _matches_target_location(location: str, target_locations: list[str], work_type_hint: str | None = None) -> bool:
    """Delegate location matching to curated US metro & All-US matcher."""
    return matches_target_location(location, target_locations, work_type_hint)


def _evaluate_title_blocklist(title: str, blocklist: list[str]) -> bool:
    lower = title.lower()
    for blocked in blocklist:
        term = blocked.strip().lower()
        if not term:
            continue
        if re.search(rf"\b{re.escape(term.strip())}", lower):
            return True
    return False


def compute_initial_relevance(
    db: Session,
    analysis: JobAnalysis,
    settings: AppSettings,
    config_manager: ConfigManager,
) -> float:
    """Score job relevance using best matching base resume, or weighted JD keyword alignment."""
    rules = config_manager.get_rules()
    resumes = list(
        db.scalars(
            select(ResumeRecord).order_by(ResumeRecord.is_base.desc(), ResumeRecord.id.desc())
        ).all()
    )
    preferred = [r for r in resumes if r.role_track == analysis.role_track]
    chosen = preferred[0] if preferred else (resumes[0] if resumes else None)

    if chosen is not None:
        canonical = CanonicalResume.model_validate_json(chosen.content_json)
        report = score_resume_against_job(
            job_id=0,
            resume_id=chosen.id,
            resume=canonical,
            job=analysis,
            rules=rules,
            settings=settings,
            raw_resume_text=chosen.raw_text or "",
        )
        return float(report.overall_score)

    # No base resume stored yet: reflect track skill alignment richness (0-100)
    matched_weight = sum(s.weight for s in analysis.weighted_skills)
    if matched_weight <= 0:
        return 35.0
    return round(min(92.0, 40.0 + matched_weight * 3.5), 1)


def fetch_greenhouse_candidates(slug: str, client: httpx.Client) -> list[RawCandidate]:
    """Fetch open jobs with full content from Greenhouse Public Boards JSON API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    resp = client.get(url)
    resp.raise_for_status()
    payload = resp.json()
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    company_name = slug.replace("-", " ").title()
    results: list[RawCandidate] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue
        loc_obj = item.get("location")
        location = loc_obj.get("name", "") if isinstance(loc_obj, dict) else str(loc_obj or "")
        raw_html = str(item.get("content") or "")
        desc = _clean_html_fragment(raw_html) if raw_html else ""
        posted_at = parse_posted_at(item.get("updated_at") or item.get("created_at"))
        results.append(
            RawCandidate(
                source=f"greenhouse:{slug}",
                title=title,
                company=company_name,
                location=location.strip(),
                url=str(item.get("absolute_url") or "") or None,
                posted_at=posted_at,
                raw_text=f"{title}\n{company_name}\n{location}\n\n{desc}".strip() if desc else None,
            )
        )
    results.sort(
        key=lambda item: item.posted_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return results


def fetch_lever_candidates(slug: str, client: httpx.Client) -> list[RawCandidate]:
    """Fetch open jobs with full descriptions from Lever Public Postings API."""
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    resp = client.get(url)
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, list):
        return []
    company_name = slug.replace("-", " ").title()
    results: list[RawCandidate] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        title = str(item.get("text") or "").strip()
        if not title:
            continue
        cats = item.get("categories") or {}
        location = str(cats.get("location") or "").strip() if isinstance(cats, dict) else ""
        workplace = str(item.get("workplaceType") or "").strip().lower()
        parts = [
            str(item.get("descriptionPlain") or ""),
            str(item.get("additionalPlain") or ""),
        ]
        for lst in item.get("lists") or []:
            if isinstance(lst, dict):
                parts.append(str(lst.get("text") or ""))
                parts.append(_clean_html_fragment(str(lst.get("content") or "")))
        desc = "\n\n".join(p.strip() for p in parts if p and p.strip())
        posted_at = parse_posted_at(item.get("createdAt"))
        results.append(
            RawCandidate(
                source=f"lever:{slug}",
                title=title,
                company=company_name,
                location=location,
                url=str(item.get("hostedUrl") or item.get("applyUrl") or "") or None,
                posted_at=posted_at,
                raw_text=f"{title}\n{company_name}\n{location}\n\n{desc}".strip() if desc else None,
                work_type_hint=workplace if workplace in ("remote", "hybrid", "onsite") else None,
            )
        )
    results.sort(
        key=lambda item: item.posted_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return results


def fetch_ashby_candidates(slug: str, client: httpx.Client) -> list[RawCandidate]:
    """Fetch open jobs with descriptions from Ashby Public Posting API."""
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    resp = client.get(url)
    resp.raise_for_status()
    payload = resp.json()
    jobs = payload.get("jobs", []) if isinstance(payload, dict) else []
    company_name = slug.replace("-", " ").title()
    results: list[RawCandidate] = []
    for item in jobs:
        if not isinstance(item, dict):
            continue
        if item.get("isListed") is False:
            continue
        title = str(item.get("title") or "").strip()
        if not title:
            continue

        loc_parts: list[str] = []
        primary_loc = str(item.get("location") or "").strip()
        if primary_loc:
            loc_parts.append(primary_loc)
        for sec in item.get("secondaryLocations") or []:
            if isinstance(sec, dict):
                sec_name = str(sec.get("location") or "").strip()
                if sec_name and sec_name not in loc_parts:
                    loc_parts.append(sec_name)
        location = "; ".join(loc_parts)

        workplace = str(item.get("workplaceType") or "").strip().lower()
        work_type_hint = (
            workplace
            if workplace in ("remote", "hybrid", "onsite")
            else ("remote" if item.get("isRemote") else None)
        )
        desc = str(item.get("descriptionPlain") or "").strip()
        if not desc and item.get("descriptionHtml"):
            desc = _clean_html_fragment(str(item.get("descriptionHtml")))

        posted_at = parse_posted_at(item.get("publishedAt"))
        results.append(
            RawCandidate(
                source=f"ashby:{slug}",
                title=title,
                company=company_name,
                location=location,
                url=str(item.get("jobUrl") or item.get("applyUrl") or "") or None,
                posted_at=posted_at,
                raw_text=f"{title}\n{company_name}\n{location}\n\n{desc}".strip() if desc else None,
                work_type_hint=work_type_hint,
            )
        )
    results.sort(
        key=lambda item: item.posted_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return results


def fetch_linkedin_candidates(
    role_query: str,
    location_query: str,
    posted_within: str,
    work_types: list[str],
    job_types: list[str],
    client: httpx.Client,
) -> list[RawCandidate]:
    """Query LinkedIn public guest search HTML endpoint using f_TPR freshness filter with pagination."""
    params_base: dict[str, str] = {
        "keywords": role_query,
        "location": location_query or "United States",
    }
    ftpr = LINKEDIN_FTPR.get(posted_within)
    if ftpr:
        params_base["f_TPR"] = ftpr
    wt_codes = []
    for wt in work_types:
        if wt == "onsite":
            wt_codes.append("1")
        elif wt == "remote":
            wt_codes.append("2")
        elif wt == "hybrid":
            wt_codes.append("3")
    if wt_codes and len(wt_codes) < 3:
        params_base["f_WT"] = ",".join(wt_codes)
    if job_types == ["full-time"]:
        params_base["f_JT"] = "F"
    elif job_types == ["contract"]:
        params_base["f_JT"] = "C"

    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    seen_card_urls: set[str] = set()
    results: list[RawCandidate] = []

    # Fetch multiple pages (up to 3 pages / 75 items) for rich candidate yields
    start_offsets = [0, 25, 50] if posted_within in ("7d", "30d", "any") else [0, 25]

    for start_offset in start_offsets:
        params = {**params_base, "start": str(start_offset)}
        try:
            resp = client.get(url, params=params, timeout=12.0)
            if resp.status_code == 429:
                break
            resp.raise_for_status()
        except Exception:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        cards = soup.find_all(["li", "div"], class_=re.compile(r"base-card|job-search-card"))
        if not cards:
            break

        for card in cards:
            title_el = card.find(class_=re.compile(r"base-search-card__title"))
            company_el = card.find(class_=re.compile(r"base-search-card__subtitle"))
            loc_el = card.find(class_=re.compile(r"job-search-card__location"))
            link_el = card.find("a", class_=re.compile(r"base-card__full-link")) or card.find("a", href=True)
            time_el = card.find("time")

            title = title_el.get_text(" ", strip=True) if title_el else ""
            company = company_el.get_text(" ", strip=True) if company_el else ""
            location = loc_el.get_text(" ", strip=True) if loc_el else ""
            href = str(link_el.get("href") or "").strip() if link_el else ""
            if not title or not href:
                continue

            canon_href = canonicalize_url(href) or href
            if canon_href in seen_card_urls:
                continue
            seen_card_urls.add(canon_href)

            time_text = time_el.get_text(" ", strip=True) if time_el else ""
            posted_at = parse_posted_at(time_text)
            if posted_at is None and time_el:
                dt_attr = str(time_el.get("datetime") or "").strip()
                # Parse date-only or timestamp attributes
                if len(dt_attr) > 10 or posted_within in ("7d", "30d", "any"):
                    posted_at = parse_posted_at(dt_attr)

            urn = str(card.get("data-entity-urn") or "")
            id_match = re.search(r"(\d{6,})", urn) or re.search(r"-(\d{6,})(?:[/?]|$)", canon_href)
            detail_url = (
                f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id_match.group(1)}"
                if id_match
                else canon_href
            )

            results.append(
                RawCandidate(
                    source="linkedin",
                    title=title,
                    company=company or "Unknown Company",
                    location=location,
                    url=canon_href,
                    posted_at=posted_at,
                    detail_url=detail_url,
                )
            )

        if len(cards) < 15:
            break

    return results


def _job_record_to_response(rec: JobPostingRecord) -> JobPostingResponse:
    analysis = JobAnalysis.model_validate(json.loads(rec.analysis_json))
    return JobPostingResponse(
        id=rec.id,
        session_id=rec.session_id,
        url=rec.url,
        analysis=analysis,
        raw_text=rec.raw_text,
        source=rec.source,
        posted_at=to_eastern(rec.posted_at),
        work_type=rec.work_type,
        job_type=rec.job_type,
        work_auth=rec.work_auth,
        disposition=rec.disposition,
        application_status=rec.application_status,
        relevance_score=rec.relevance_score,
        created_at=to_eastern(rec.created_at),
    )


def run_batch_scrape(
    db: Session,
    session_rec: ScrapeSessionRecord,
    req: ScrapeBatchRequest,
    config_manager: ConfigManager,
    client: httpx.Client | None = None,
    now: datetime | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> ScrapeBatchResult:
    """Pull postings across target roles and apply simultaneous inline filtering + permanent deduplication."""
    settings = config_manager.get_settings()
    all_tracks = config_manager.list_role_tracks()
    track_map = {t.id: t for t in all_tracks}

    posted_within = req.posted_within or settings.posted_within_default or "24h"
    selected_track_ids = req.role_tracks or settings.target_role_tracks or [t.id for t in all_tracks]
    selected_tracks = [track_map[tid] for tid in selected_track_ids if tid in track_map]
    raw_locations = req.locations if req.locations is not None else settings.target_locations
    # Default exclusively to US & US-compatible Remote when no city list is configured
    target_locations = list(raw_locations) if raw_locations else ["ALL_US"]
    sources = req.sources if req.sources is not None else settings.scraper_sources
    boards = req.company_boards if req.company_boards is not None else settings.company_boards
    ref_now = now or datetime.now(timezone.utc)

    active_boards: list[tuple[str, str, str]] = []
    for entry in boards:
        if ":" not in entry:
            continue
        provider, slug = entry.split(":", 1)
        provider = provider.strip().lower()
        slug = slug.strip()
        if slug and provider in sources:
            active_boards.append((entry, provider, slug))

    wants_national = (
        not target_locations
        or any(
            loc.strip().lower() in ("all_us", "all us", "all us cities", "united states", "usa")
            for loc in target_locations
        )
        or len(target_locations) > 4
    )
    li_locations = (
        ["United States"]
        if wants_national
        else [
            ("United States" if loc.strip().lower() == "remote" else loc)
            for loc in target_locations[:4]
        ]
    )
    li_queries: list[tuple[RoleTrackConfig, str, str]] = []
    if "linkedin" in sources and selected_tracks and li_locations:
        seen_li_keys: set[tuple[str, str]] = set()
        for loc in li_locations:
            for track in selected_tracks:
                clean_q = (
                    track.search_query or re.sub(r"\([^)]*\)", "", track.display_name)
                ).strip()
                key = (clean_q.lower(), loc.lower())
                if clean_q and key not in seen_li_keys:
                    seen_li_keys.add(key)
                    li_queries.append((track, clean_q, loc))
                if len(li_queries) >= 12:
                    break
            if len(li_queries) >= 12:
                break
    steps_total = max(1, len(active_boards) + len(li_queries))
    steps_completed = 0

    def _emit(**kwargs: Any) -> None:
        if progress_callback:
            progress_callback(kwargs)

    owns_client = client is None
    http_client = client or httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0)
    candidates: list[RawCandidate] = []
    source_notes: list[str] = []
    cancelled = False
    stopped_during_fetch = False

    try:
        _emit(
            phase="Fetching boards",
            current_source="Starting...",
            steps_completed=0,
            steps_total=steps_total,
            scanned_count=0,
        )

        # 1. Company ATS boards (Greenhouse / Lever / Ashby)
        for entry, provider, slug in active_boards:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                stopped_during_fetch = True
                break
            _emit(
                phase="Fetching boards",
                current_source=entry,
                steps_completed=steps_completed,
                steps_total=steps_total,
                scanned_count=len(candidates),
            )
            try:
                if provider == "greenhouse":
                    fetched = fetch_greenhouse_candidates(slug, http_client)[: req.max_per_source]
                    candidates.extend(fetched)
                elif provider == "lever":
                    fetched = fetch_lever_candidates(slug, http_client)[: req.max_per_source]
                    candidates.extend(fetched)
                elif provider == "ashby":
                    fetched = fetch_ashby_candidates(slug, http_client)[: req.max_per_source]
                    candidates.extend(fetched)
            except Exception as exc:
                source_notes.append(f"{entry}: {exc}")
            steps_completed += 1
            _emit(
                phase="Fetching boards",
                current_source=entry,
                steps_completed=steps_completed,
                steps_total=steps_total,
                scanned_count=len(candidates),
                source_notes=list(source_notes),
            )

        # 2. LinkedIn public guest search across target role tracks & locations
        if not cancelled:
            for track, clean_query, loc in li_queries:
                if cancel_event and cancel_event.is_set():
                    cancelled = True
                    stopped_during_fetch = True
                    break
                step_label = f"linkedin ({clean_query} · {loc})"
                _emit(
                    phase="Fetching LinkedIn",
                    current_source=step_label,
                    steps_completed=steps_completed,
                    steps_total=steps_total,
                    scanned_count=len(candidates),
                )
                for attempt in range(2 if owns_client else 1):
                    try:
                        if owns_client and _sleep_or_cancel(0.85 if attempt == 0 else 2.2, cancel_event):
                            cancelled = True
                            stopped_during_fetch = True
                            break
                        fetched = fetch_linkedin_candidates(
                            role_query=clean_query,
                            location_query=loc,
                            posted_within=posted_within,
                            work_types=list(settings.work_types),
                            job_types=list(settings.job_types),
                            client=http_client,
                        )[: req.max_per_source]
                        candidates.extend(fetched)
                        break
                    except httpx.HTTPStatusError as exc:
                        if owns_client and exc.response.status_code == 429 and attempt == 0:
                            continue
                        source_notes.append(f"linkedin ({clean_query} / {loc}): {exc}")
                        break
                    except Exception as exc:
                        source_notes.append(f"linkedin ({clean_query} / {loc}): {exc}")
                        break
                if cancelled:
                    break
                steps_completed += 1
                _emit(
                    phase="Fetching LinkedIn",
                    current_source=step_label,
                    steps_completed=steps_completed,
                    steps_total=steps_total,
                    scanned_count=len(candidates),
                    source_notes=list(source_notes),
                )

        # 3. Simultaneous inline two-stage filtering loop
        work_candidates = (
            [c for c in candidates if (c.raw_text or "").strip()]
            if stopped_during_fetch
            else candidates
        )
        scanned_count = len(work_candidates)
        processed_count = 0
        saved_jobs: list[JobPostingResponse] = []
        filtered_samples: list[FilteredJobSample] = []
        filter_breakdown: dict[str, int] = {}
        duplicate_skipped_count = 0
        seen_in_batch_urls: set[str] = set()
        seen_in_batch_cross_fps: set[tuple[str, str]] = set()
        existing_filtered_keys: set[tuple[str, str, str]] = {
            (r.url_hash, r.category, r.filter_reason)
            for r in db.scalars(
                select(SessionFilteredJobRecord).where(
                    SessionFilteredJobRecord.session_id == session_rec.id
                )
            ).all()
        }
        prior_audit_by_hash: dict[str, tuple[list[str], list[str]]] = {}
        for prev_row in db.scalars(
            select(SessionFilteredJobRecord)
            .where(SessionFilteredJobRecord.category == "auto_filtered")
            .order_by(SessionFilteredJobRecord.id.desc())
            .limit(800)
        ).all():
            if prev_row.url_hash and prev_row.url_hash not in prior_audit_by_hash:
                try:
                    prev_reasons = json.loads(prev_row.filter_reasons_json or "[]")
                except ValueError:
                    prev_reasons = []
                if not prev_reasons and prev_row.filter_reason:
                    prev_reasons = [prev_row.filter_reason]
                try:
                    prev_notes = json.loads(prev_row.suitability_details_json or "[]")
                except ValueError:
                    prev_notes = []
                prior_audit_by_hash[prev_row.url_hash] = (prev_reasons, prev_notes)

        def _record_session_audit(
            cand: RawCandidate,
            *,
            category: str,
            reason: str,
            fp: str,
            u_hash: str | None,
            role_track_id: str,
            full_text: str = "",
            all_reasons: list[str] | None = None,
            suitability_notes: list[str] | None = None,
        ) -> None:
            effective_hash = u_hash or hash_url(cand.url) or fp
            audit_key = (effective_hash, category, reason)
            if audit_key in existing_filtered_keys:
                return
            existing_filtered_keys.add(audit_key)
            deduped_reasons: list[str] = []
            for r_item in [reason, *(all_reasons or [])]:
                if r_item and r_item not in deduped_reasons:
                    deduped_reasons.append(r_item)
            deduped_notes: list[str] = []
            for note in (suitability_notes or []):
                if note and note not in deduped_notes:
                    deduped_notes.append(note)
            db.add(
                SessionFilteredJobRecord(
                    session_id=session_rec.id,
                    url=(canonicalize_url(cand.url) or cand.url or "")[:1024],
                    url_hash=effective_hash[:64],
                    title=(cand.title or "Untitled Role")[:256],
                    company=(cand.company or "Unknown Company")[:256],
                    source=(cand.source or "unknown")[:64],
                    location=(cand.location or "")[:256],
                    role_track=role_track_id[:64],
                    category=category,
                    filter_reason=reason[:128],
                    filter_reasons_json=json.dumps(deduped_reasons),
                    suitability_details_json=json.dumps(deduped_notes),
                    posted_at=cand.posted_at,
                    raw_text=full_text or cand.raw_text or "",
                )
            )

        def _drop(
            cand: RawCandidate,
            reason: str,
            fp: str,
            u_hash: str | None,
            *,
            persist_seen: bool,
            role_track_id: str | None = None,
            full_text: str = "",
            all_reasons: list[str] | None = None,
            suitability_notes: list[str] | None = None,
        ) -> None:
            filter_breakdown[reason] = filter_breakdown.get(reason, 0) + 1
            resolved_track = role_track_id or config_manager.infer_role_track_for_title(
                cand.title,
                preferred_ids=settings.target_role_tracks,
            )
            _record_session_audit(
                cand,
                category="auto_filtered",
                reason=reason,
                fp=fp,
                u_hash=u_hash,
                role_track_id=resolved_track,
                full_text=full_text,
                all_reasons=all_reasons or [reason],
                suitability_notes=suitability_notes,
            )
            if persist_seen:
                record_seen_job(
                    db,
                    url=cand.url,
                    url_hash=u_hash,
                    content_fingerprint=fp,
                    company=cand.company,
                    title=cand.title,
                    location=cand.location,
                    source=cand.source,
                    disposition="auto_filtered",
                    filter_reason=reason,
                    session_id=session_rec.id,
                )
            if len(filtered_samples) < 25:
                filtered_samples.append(
                    FilteredJobSample(
                        title=cand.title,
                        company=cand.company,
                        location=cand.location,
                        source=cand.source,
                        reason=reason,
                        url=cand.url,
                    )
                )

        _emit(
            phase="Filtering & analyzing JDs",
            current_source=f"Analyzing {scanned_count} candidates...",
            steps_completed=steps_total if not cancelled else steps_completed,
            steps_total=steps_total,
            scanned_count=scanned_count,
            processed_count=0,
        )

        for idx, cand in enumerate(work_candidates, start=1):
            if not stopped_during_fetch and cancel_event and cancel_event.is_set():
                cancelled = True
                break
            processed_count += 1
            if idx % 5 == 0:
                try:
                    db.commit()
                except Exception:
                    pass
            if idx % 10 == 0 or "linkedin" in cand.source:
                _emit(
                    phase="Filtering & analyzing JDs",
                    current_source=f"{cand.company} — {cand.title}"[:80],
                    scanned_count=scanned_count,
                    processed_count=processed_count,
                    saved_count=len(saved_jobs),
                    filtered_count=sum(filter_breakdown.values()),
                    duplicate_skipped_count=duplicate_skipped_count,
                    filter_breakdown=dict(filter_breakdown),
                    source_notes=list(source_notes),
                )
            canon_u = canonicalize_url(cand.url)
            u_hash = hash_url(canon_u)
            fp = make_content_fingerprint(cand.company, cand.title, cand.location)
            inferred_track_id = config_manager.infer_role_track_for_title(
                cand.title,
                preferred_ids=settings.target_role_tracks,
            )

            # In-batch duplicate guard (same canonical URL OR exact same posting on different board)
            batch_dup = False
            if u_hash:
                if u_hash in seen_in_batch_urls:
                    batch_dup = True
                seen_in_batch_urls.add(u_hash)
            if not batch_dup:
                for seen_fp, seen_src in seen_in_batch_cross_fps:
                    if seen_fp == fp and (not u_hash or seen_src != cand.source):
                        batch_dup = True
                        break
                seen_in_batch_cross_fps.add((fp, cand.source))
            if batch_dup:
                duplicate_skipped_count += 1
                filter_breakdown["duplicate_in_batch"] = filter_breakdown.get("duplicate_in_batch", 0) + 1
                _record_session_audit(
                    cand,
                    category="seen_skipped",
                    reason="duplicate_in_batch",
                    fp=fp,
                    u_hash=u_hash,
                    role_track_id=inferred_track_id,
                    all_reasons=["duplicate_in_batch"],
                    suitability_notes=["Duplicate posting appeared twice in this batch scrape."],
                )
                continue

            # Prior progress check across sessions before skipping:
            # If candidate appeared in a prior session and has progress (applied, interviewing, screening, offer, resume created),
            # carry it forward into this session with its status intact so it appears in the applied/in-progress pile.
            prior_job: JobPostingRecord | None = None
            if u_hash:
                prior_job = db.scalars(
                    select(JobPostingRecord)
                    .where(JobPostingRecord.url_hash == u_hash)
                    .order_by(JobPostingRecord.id.desc())
                ).first()
            if prior_job is None and fp:
                for cand_pj in db.scalars(
                    select(JobPostingRecord)
                    .where(JobPostingRecord.content_fingerprint == fp)
                    .order_by(JobPostingRecord.id.desc())
                ).all():
                    if u_hash and cand_pj.url_hash and cand_pj.url_hash != u_hash and cand.source and cand_pj.source == cand.source:
                        continue
                    prior_job = cand_pj
                    break

            if prior_job is not None:
                if prior_job.session_id == session_rec.id:
                    duplicate_skipped_count += 1
                    filter_breakdown["duplicate_in_session"] = filter_breakdown.get("duplicate_in_session", 0) + 1
                    _record_session_audit(
                        cand,
                        category="seen_skipped",
                        reason="duplicate_in_session",
                        fp=fp,
                        u_hash=u_hash,
                        role_track_id=inferred_track_id,
                        all_reasons=["duplicate_in_session"],
                        suitability_notes=["Posting already saved in this session."],
                    )
                    continue

                if prior_job.disposition == "discarded" or prior_job.application_status == "rejected":
                    duplicate_skipped_count += 1
                    filter_breakdown["seen:discarded"] = filter_breakdown.get("seen:discarded", 0) + 1
                    _record_session_audit(
                        cand,
                        category="seen_skipped",
                        reason="seen:discarded",
                        fp=fp,
                        u_hash=u_hash,
                        role_track_id=inferred_track_id,
                        all_reasons=["seen:discarded"],
                        suitability_notes=["Previously discarded or rejected in an earlier session."],
                    )
                    continue

                has_progress = (
                    prior_job.application_status in ("applied", "screening", "interviewing", "offer", "resume_created")
                    or prior_job.applied_at is not None
                    or bool((prior_job.application_notes or "").strip())
                )
                if has_progress:
                    already_in_batch = any(
                        (sj.url_hash and sj.url_hash == u_hash) or
                        (sj.content_fingerprint == fp and sj.source == (cand.source or prior_job.source))
                        for sj in saved_jobs
                    )
                    if not already_in_batch:
                        orig_sess = prior_job.session_id or "Prior"
                        carried_tag = f"[Carried from Session {orig_sess} • {prior_job.application_status}]"
                        p_notes = (prior_job.application_notes or "").strip()
                        new_notes = f"{p_notes}\n{carried_tag}".strip() if carried_tag not in p_notes else p_notes

                        resolved_company = cand.company if cand.company and cand.company != "Unknown Company" else prior_job.company
                        resolved_title = cand.title if cand.title and cand.title != "Untitled Role" else prior_job.title
                        resolved_loc = cand.location or prior_job.location
                        carried_analysis_json = prior_job.analysis_json
                        if resolved_company != prior_job.company or resolved_title != prior_job.title:
                            try:
                                a_dict = json.loads(carried_analysis_json)
                                a_dict["company"] = resolved_company
                                a_dict["title"] = resolved_title
                                if resolved_loc:
                                    a_dict["location"] = resolved_loc
                                carried_analysis_json = json.dumps(a_dict)
                            except Exception:
                                pass

                        carried_job = JobPostingRecord(
                            session_id=session_rec.id,
                            url=cand.url or prior_job.url,
                            company=resolved_company,
                            title=resolved_title,
                            role_track=prior_job.role_track or inferred_track_id,
                            location=resolved_loc,
                            yoe_min=prior_job.yoe_min,
                            yoe_max=prior_job.yoe_max,
                            salary_min=prior_job.salary_min,
                            salary_max=prior_job.salary_max,
                            salary_currency=prior_job.salary_currency,
                            raw_text=prior_job.raw_text,
                            analysis_json=carried_analysis_json,
                            url_hash=u_hash,
                            content_fingerprint=fp,
                            source=cand.source or prior_job.source,
                            posted_at=cand.posted_at or prior_job.posted_at,
                            work_type=prior_job.work_type,
                            job_type=prior_job.job_type,
                            work_auth=prior_job.work_auth,
                            disposition="saved",
                            application_status=prior_job.application_status,
                            applied_at=prior_job.applied_at,
                            application_notes=new_notes,
                            relevance_score=prior_job.relevance_score,
                        )
                        db.add(carried_job)
                        db.flush()

                        prior_run = db.scalars(
                            select(TailoringRunRecord)
                            .where(TailoringRunRecord.job_id == prior_job.id)
                            .order_by(TailoringRunRecord.id.desc())
                        ).first()
                        if prior_run is not None:
                            carried_run = TailoringRunRecord(
                                job_id=carried_job.id,
                                resume_id=prior_run.resume_id,
                                base_score=prior_run.base_score,
                                tailored_score=prior_run.tailored_score,
                                report_json=prior_run.report_json,
                                tailored_resume_json=prior_run.tailored_resume_json,
                                output_folder=prior_run.output_folder,
                            )
                            db.add(carried_run)
                            db.flush()

                        saved_jobs.append(_job_record_to_response(carried_job))
                        _record_session_audit(
                            cand,
                            category="saved",
                            reason=f"carried_forward:{prior_job.application_status}",
                            fp=fp,
                            u_hash=u_hash,
                            role_track_id=carried_job.role_track,
                            all_reasons=["carried_forward_progress"],
                            suitability_notes=[f"Carried forward active progress ({prior_job.application_status}) from Session {orig_sess}."],
                        )
                    else:
                        duplicate_skipped_count += 1
                    continue

            # Gate 1A: Permanent seen/discarded ledger check BEFORE full JD fetch
            already_seen, seen_reason = is_job_already_seen(db, u_hash, fp, cand.source)
            if already_seen:
                duplicate_skipped_count += 1
                reason_key = seen_reason or "already_seen"
                filter_breakdown[reason_key] = filter_breakdown.get(reason_key, 0) + 1
                prev_reasons, prev_notes = prior_audit_by_hash.get(u_hash or "", ([], []))
                seen_summary_note = (
                    "Already saved in this or a prior session."
                    if reason_key == "seen:saved"
                    else (
                        "Previously discarded by you in an earlier session."
                        if reason_key == "seen:discarded"
                        else "Matched permanent filter history from an earlier scrape."
                    )
                )
                _record_session_audit(
                    cand,
                    category="seen_skipped",
                    reason=reason_key,
                    fp=fp,
                    u_hash=u_hash,
                    role_track_id=inferred_track_id,
                    all_reasons=[reason_key, *prev_reasons],
                    suitability_notes=[seen_summary_note, *prev_notes],
                )
                continue

            # Collect ALL unsuitability reasons rather than stopping on first mismatch.
            # Primary Gate 1 Filter #1: Location / US-Only Guard
            gate_reasons: list[str] = []
            suitability_notes: list[str] = []

            if cand.location and not _matches_target_location(
                cand.location, target_locations, cand.work_type_hint
            ):
                gate_reasons.append("location_mismatch")
                if not is_us_or_remote_location(cand.location, cand.work_type_hint):
                    suitability_notes.append(f"Outside US / non-US location: '{cand.location}'")
                else:
                    suitability_notes.append(
                        f"US location '{cand.location}' outside selected target cities"
                    )

            # Gate 1 Filter #2: Freshness window
            if not is_within_freshness(cand.posted_at, posted_within, ref_now):
                gate_reasons.append("stale_outside_window")
                if cand.posted_at is not None:
                    aware_dt = (
                        cand.posted_at
                        if cand.posted_at.tzinfo
                        else cand.posted_at.replace(tzinfo=timezone.utc)
                    )
                    age_hrs = max(0.0, (ref_now - aware_dt).total_seconds() / 3600.0)
                    age_lbl = (
                        f"{round(age_hrs, 1)}h ago"
                        if age_hrs < 48
                        else f"{int(round(age_hrs / 24.0))}d ago"
                    )
                    suitability_notes.append(
                        f"Posted {age_lbl} — outside '{posted_within}' window"
                    )
                else:
                    suitability_notes.append(f"Outside '{posted_within}' freshness window")

            # Gate 1 Filter #3: Title blocklist keywords
            title_lower = cand.title.lower()
            matched_block_terms = [
                term.strip()
                for term in settings.title_blocklist
                if term.strip() and re.search(rf"\b{re.escape(term.strip().lower())}", title_lower)
            ]
            if matched_block_terms:
                gate_reasons.append("blocked_title")
                suitability_notes.append(
                    f"Title contains blocked keyword(s): {', '.join(matched_block_terms[:4])}"
                )

            # Gate 1 Filter #4: Target role track match
            matched_track = _match_target_role(cand.title, selected_tracks)
            if selected_tracks and matched_track is None:
                gate_reasons.append("role_mismatch")
                target_names = ", ".join(t.display_name for t in selected_tracks[:4])
                suitability_notes.append(
                    f"Title does not match target role(s): {target_names}"
                )

            resolved_track_id = matched_track.id if matched_track else inferred_track_id

            # Fetch full JD text if only a summary card was available AND Gate 1 passed
            full_text = cand.raw_text or ""
            if not full_text and not gate_reasons:
                fetch_target = cand.detail_url or canon_u or cand.url
                if fetch_target:
                    last_exc: Exception | None = None
                    detail_cancelled = False
                    for attempt in range(3 if (owns_client and "linkedin" in cand.source) else 1):
                        if not stopped_during_fetch and cancel_event and cancel_event.is_set():
                            detail_cancelled = True
                            break
                        try:
                            if owns_client and "linkedin" in cand.source:
                                if _sleep_or_cancel(1.1 if attempt == 0 else 2.5 * attempt, cancel_event):
                                    detail_cancelled = True
                                    break
                            scraped = fetch_job_posting(url=fetch_target, client=http_client)
                            full_text = scraped.raw_text
                            last_exc = None
                            break
                        except Exception as exc:
                            last_exc = exc
                            if "429" not in str(exc):
                                break
                    if detail_cancelled:
                        cancelled = True
                        processed_count -= 1
                        break
                    if last_exc is not None:
                        _drop(
                            cand,
                            "fetch_failed",
                            fp,
                            u_hash,
                            persist_seen=False,
                            role_track_id=resolved_track_id,
                            all_reasons=["fetch_failed"],
                            suitability_notes=[f"Failed to fetch full job description: {last_exc}"],
                        )
                        source_notes.append(f"detail {cand.company} ({cand.title}): {last_exc}")
                        continue

            if not full_text.strip():
                if gate_reasons:
                    persist = any(
                        r not in ("stale_outside_window", "fetch_failed", "empty_jd")
                        for r in gate_reasons
                    )
                    _drop(
                        cand,
                        gate_reasons[0],
                        fp,
                        u_hash,
                        persist_seen=persist,
                        role_track_id=resolved_track_id,
                        all_reasons=gate_reasons,
                        suitability_notes=suitability_notes,
                    )
                    continue
                _drop(
                    cand,
                    "empty_jd",
                    fp,
                    u_hash,
                    persist_seen=False,
                    role_track_id=resolved_track_id,
                    all_reasons=["empty_jd"],
                    suitability_notes=["Job posting had an empty description."],
                )
                continue

            # Gate 2: Full JD deterministic analysis & multi-reason filter rules
            target_track = matched_track or config_manager.get_role_track(
                config_manager.infer_role_track_for_title(
                    cand.title,
                    preferred_ids=settings.target_role_tracks,
                )
            )
            analysis = analyze_job_posting(
                raw_text=full_text,
                role_track=target_track,
                settings=settings,
                scraped_title=cand.title,
                scraped_company=cand.company,
                scraped_location=cand.location,
            )

            # Work arrangement check (only filter if explicitly stated and excluded)
            if (
                settings.work_types
                and analysis.work_type != "unspecified"
                and analysis.work_type not in settings.work_types
            ):
                gate_reasons.append(f"work_type:{analysis.work_type}")
                suitability_notes.append(
                    f"Work mode '{analysis.work_type}' excluded (allowed: {', '.join(settings.work_types)})"
                )

            # Employment type check (full-time vs contract)
            if settings.job_types and analysis.job_type not in settings.job_types:
                gate_reasons.append(f"job_type:{analysis.job_type}")
                suitability_notes.append(
                    f"Employment type '{analysis.job_type}' excluded (allowed: {', '.join(settings.job_types)})"
                )

            # Work authorization / H-1B check
            if settings.work_authorization == "h1b" and analysis.work_auth == "no_sponsorship":
                gate_reasons.append("no_h1b_sponsorship")
                suitability_notes.append("Explicitly states no H-1B / visa sponsorship")

            # Compensation floor ONLY when explicit USD salary is stated; omitted salary is KEPT
            sal = analysis.salary
            if sal.min_amount is not None and sal.currency == "USD":
                top_val = sal.max_amount if sal.max_amount is not None else sal.min_amount
                if (
                    sal.period == "year"
                    and settings.target_salary_min is not None
                    and top_val < settings.target_salary_min
                ):
                    gate_reasons.append("below_min_salary")
                    suitability_notes.append(
                        f"Compensation up to ${top_val:,}/yr is below ${settings.target_salary_min:,}/yr min"
                    )
                if (
                    sal.period == "hour"
                    and settings.min_hourly_rate is not None
                    and top_val < settings.min_hourly_rate
                ):
                    gate_reasons.append("below_min_hourly")
                    suitability_notes.append(
                        f"Hourly compensation ${top_val}/hr is below ${settings.min_hourly_rate}/hr min"
                    )

            # Years-of-experience guard when explicit floor/ceiling bounds are configured
            yoe = analysis.yoe
            if (
                settings.target_yoe_max is not None
                and yoe.min_years is not None
                and yoe.min_years > settings.target_yoe_max + 2
            ):
                gate_reasons.append("yoe_too_high")
                suitability_notes.append(
                    f"Requires {yoe.min_years}+ yrs experience (above your {settings.target_yoe_max} yr ceiling)"
                )
            if (
                settings.target_yoe_min is not None
                and yoe.max_years is not None
                and yoe.max_years < max(0, settings.target_yoe_min - 2)
            ):
                gate_reasons.append("yoe_too_low")
                suitability_notes.append(
                    f"Max {yoe.max_years} yrs experience (below your {settings.target_yoe_min} yr minimum)"
                )

            # Initial relevance score against best available base resume
            rel_score = compute_initial_relevance(db, analysis, settings, config_manager)
            if settings.min_relevance_score > 0 and rel_score < settings.min_relevance_score:
                gate_reasons.append("below_min_relevance")
                suitability_notes.append(
                    f"Match score {round(rel_score)}% is below your {settings.min_relevance_score}% threshold"
                )

            if gate_reasons:
                deduped_reasons: list[str] = []
                for gr in gate_reasons:
                    if gr not in deduped_reasons:
                        deduped_reasons.append(gr)
                persist = any(
                    r not in ("stale_outside_window", "fetch_failed", "empty_jd")
                    for r in deduped_reasons
                )
                _drop(
                    cand,
                    deduped_reasons[0],
                    fp,
                    u_hash,
                    persist_seen=persist,
                    role_track_id=target_track.id,
                    full_text=full_text,
                    all_reasons=deduped_reasons,
                    suitability_notes=suitability_notes,
                )
                continue

            # Passed both gates -> Save immediately to session & ledger
            job_rec = JobPostingRecord(
                session_id=session_rec.id,
                url=canon_u or cand.url,
                company=analysis.company,
                title=analysis.title,
                location=analysis.location,
                role_track=analysis.role_track,
                salary_min=analysis.salary.min_amount,
                salary_max=analysis.salary.max_amount,
                salary_currency=analysis.salary.currency,
                yoe_min=analysis.yoe.min_years,
                yoe_max=analysis.yoe.max_years,
                raw_text=full_text,
                analysis_json=json.dumps(analysis.model_dump(mode="json")),
                url_hash=u_hash,
                content_fingerprint=fp,
                source=cand.source,
                posted_at=cand.posted_at,
                work_type=analysis.work_type,
                job_type=analysis.job_type,
                work_auth=analysis.work_auth,
                disposition="kept",
                application_status="ready",
                relevance_score=rel_score,
            )
            db.add(job_rec)
            db.flush()
            record_seen_job(
                db,
                url=canon_u or cand.url,
                url_hash=u_hash,
                content_fingerprint=fp,
                company=analysis.company,
                title=analysis.title,
                location=analysis.location,
                source=cand.source,
                disposition="saved",
                filter_reason=None,
                session_id=session_rec.id,
            )
            saved_jobs.append(_job_record_to_response(job_rec))

        # Update session scrape metrics atomically
        if cancelled:
            source_notes.append("Scrape stopped early by user.")
        filtered_total = sum(filter_breakdown.values())
        session_rec.posted_within = posted_within
        session_rec.scanned_count += processed_count
        session_rec.saved_count += len(saved_jobs)
        session_rec.filtered_count += filtered_total

        prev_breakdown = json.loads(session_rec.filter_breakdown_json or "{}")
        for k, v in filter_breakdown.items():
            prev_breakdown[k] = prev_breakdown.get(k, 0) + v
        session_rec.filter_breakdown_json = json.dumps(prev_breakdown)

        prev_notes = json.loads(session_rec.source_notes_json or "[]")
        session_rec.source_notes_json = json.dumps((prev_notes + source_notes)[-20:])

        db.commit()
        result = ScrapeBatchResult(
            session_id=session_rec.id,
            posted_within=posted_within,
            scanned_count=processed_count,
            saved_count=len(saved_jobs),
            filtered_count=filtered_total,
            duplicate_skipped_count=duplicate_skipped_count,
            filter_breakdown=filter_breakdown,
            source_notes=source_notes,
            saved_jobs=saved_jobs,
            filtered_samples=filtered_samples,
            cancelled=cancelled,
        )
        _emit(
            phase="Stopped" if cancelled else "Completed",
            current_source="Stopped by user" if cancelled else "Done",
            steps_completed=steps_completed if cancelled else steps_total,
            steps_total=steps_total,
            scanned_count=processed_count,
            processed_count=processed_count,
            saved_count=len(saved_jobs),
            filtered_count=filtered_total,
            duplicate_skipped_count=duplicate_skipped_count,
            filter_breakdown=dict(filter_breakdown),
            source_notes=list(source_notes),
        )
        return result
    finally:
        if owns_client:
            http_client.close()


class ScrapeProgressStore:
    """Thread-safe per-app store tracking live and completed background batch scrapes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[int, ScrapeProgressResponse] = {}
        self._cancel_events: dict[int, threading.Event] = {}

    def get(self, session_id: int) -> ScrapeProgressResponse:
        with self._lock:
            state = self._states.get(session_id)
            if state is None:
                return ScrapeProgressResponse(session_id=session_id, status="idle")
            return state.model_copy(deep=True)

    def cancel(self, session_id: int) -> ScrapeProgressResponse:
        with self._lock:
            ev = self._cancel_events.get(session_id)
            if ev is not None:
                ev.set()
            cur = self._states.get(session_id)
            if cur is not None and cur.status == "running":
                merged = cur.model_dump()
                merged["phase"] = "Stopping..."
                merged["current_source"] = "Finishing current step & saving progress..."
                self._states[session_id] = ScrapeProgressResponse.model_validate(merged)
                return self._states[session_id].model_copy(deep=True)
            if cur is not None:
                return cur.model_copy(deep=True)
            return ScrapeProgressResponse(session_id=session_id, status="idle")

    def start(
        self,
        *,
        session_id: int,
        session_factory: sessionmaker[Session],
        config_manager: ConfigManager,
        req: ScrapeBatchRequest,
        client_override: httpx.Client | None = None,
    ) -> ScrapeProgressResponse:
        with self._lock:
            existing = self._states.get(session_id)
            if existing is not None and existing.status == "running":
                return existing.model_copy(deep=True)
            cancel_event = threading.Event()
            self._cancel_events[session_id] = cancel_event
            initial = ScrapeProgressResponse(
                session_id=session_id,
                status="running",
                phase="Queued",
                current_source="Initializing...",
            )
            self._states[session_id] = initial

        def _update(fields: dict[str, Any]) -> None:
            with self._lock:
                cur = self._states.get(session_id)
                if cur is None:
                    return
                merged = cur.model_dump()
                # Keep user-requested "Stopping..." banner visible until finalization
                if cur.status == "running" and cancel_event.is_set() and fields.get("status") is None:
                    fields = dict(fields)
                    fields["phase"] = "Stopping..."
                merged.update(fields)
                self._states[session_id] = ScrapeProgressResponse.model_validate(merged)

        def _runner() -> None:
            try:
                with session_factory() as db:
                    session_row = db.get(ScrapeSessionRecord, session_id)
                    if session_row is None:
                        _update({"status": "failed", "phase": "Failed", "error": "Scrape session not found."})
                        return
                    result = run_batch_scrape(
                        db=db,
                        session_rec=session_row,
                        req=req,
                        config_manager=config_manager,
                        client=client_override,
                        progress_callback=_update,
                        cancel_event=cancel_event,
                    )
                    final_status = "cancelled" if (result.cancelled or cancel_event.is_set()) else "completed"
                    _update(
                        {
                            "status": final_status,
                            "phase": "Stopped" if final_status == "cancelled" else "Completed",
                            "current_source": "Stopped by user" if final_status == "cancelled" else "Done",
                            "scanned_count": result.scanned_count,
                            "processed_count": result.scanned_count,
                            "saved_count": result.saved_count,
                            "filtered_count": result.filtered_count,
                            "duplicate_skipped_count": result.duplicate_skipped_count,
                            "filter_breakdown": dict(result.filter_breakdown),
                            "source_notes": list(result.source_notes),
                            "result": result,
                        }
                    )
            except Exception as exc:
                _update({"status": "failed", "phase": "Failed", "error": str(exc)})

        worker = threading.Thread(target=_runner, daemon=True, name=f"scrape-session-{session_id}")
        worker.start()
        return self.get(session_id)
