"""Automated multi-source job scraper with simultaneous inline filtering and permanent deduplication."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import JobPostingRecord, ResumeRecord, ScrapeSessionRecord, SeenJobFingerprintRecord
from backend.app.schemas.config import AppSettings, RoleTrackConfig
from backend.app.schemas.job import (
    FilteredJobSample,
    JobAnalysis,
    JobPostingResponse,
    ScrapeBatchRequest,
    ScrapeBatchResult,
)
from backend.app.schemas.resume import CanonicalResume
from backend.app.services.ats_scorer import score_resume_against_job
from backend.app.services.config_manager import ConfigManager
from backend.app.services.jd_analyzer import _keyword_pattern, analyze_job_posting
from backend.app.services.scraper import DEFAULT_HEADERS, _clean_html_fragment, fetch_job_posting

FRESHNESS_SECONDS: dict[str, int | None] = {
    "1h": 3600,
    "12h": 43200,
    "24h": 86400,
    "7d": 604800,
    "any": None,
}

LINKEDIN_FTPR: dict[str, str] = {
    "1h": "r3600",
    "12h": "r43200",
    "24h": "r86400",
    "7d": "r604800",
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

_CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "seattle": ("seattle", "bellevue", "redmond", "kirkland", "greater seattle", "wa"),
    "san diego": ("san diego", "la jolla", "carlsbad", "sorrento valley"),
    "san francisco": ("san francisco", "sf", "bay area", "oakland", "palo alto", "menlo park", "mountain view", "sunnyvale", "san jose", "south san francisco"),
    "new york": ("new york", "nyc", "manhattan", "brooklyn"),
    "austin": ("austin",),
    "boston": ("boston", "cambridge"),
    "remote": ("remote", "distributed", "work from home", "anywhere in us", "united states (remote)"),
}


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


_ROLE_NOUNS = {"engineer", "developer", "architect", "sde", "fde", "scientist", "mts"}


def _match_target_role(
    title: str,
    selected_tracks: list[RoleTrackConfig],
) -> RoleTrackConfig | None:
    """Match a posting title against selected role tracks via word-bounded aliases."""
    if not selected_tracks:
        return None
    lower = f" {re.sub(r'\bsr\.?\b', 'senior', title.lower())} "
    title_tokens = set(re.findall(r"[a-z0-9]+", lower))
    has_role_noun = bool(title_tokens & _ROLE_NOUNS)
    best_track: RoleTrackConfig | None = None
    best_score = 0

    for track in selected_tracks:
        clean_display = re.sub(r"\([^)]*\)", "", track.display_name).strip()
        candidates = [track.display_name, clean_display, *track.aliases]
        for alias in candidates:
            norm_alias = alias.strip().lower()
            if not norm_alias:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(norm_alias)}(?![a-z0-9])", lower):
                score = len(norm_alias) + 10
                if score > best_score:
                    best_score = score
                    best_track = track
            elif has_role_noun:
                # Multi-word distinctive token fallback (requires >=2 non-generic words + role noun)
                alias_tokens = [tok for tok in re.findall(r"[a-z0-9]+", norm_alias) if len(tok) > 2]
                generic_skip = {"senior", "staff", "lead", "principal", "engineer", "developer", "level", "software"}
                distinctive = [tok for tok in alias_tokens if tok not in generic_skip]
                if len(distinctive) >= 2 and all(tok in title_tokens for tok in distinctive):
                    score = sum(len(t) for t in distinctive)
                    if score > best_score:
                        best_score = score
                        best_track = track

    return best_track


def _matches_target_location(location: str, target_locations: list[str], work_type_hint: str | None = None) -> bool:
    """Return True if target_locations is empty, posting location matches a target, or is remote."""
    if not target_locations:
        return True
    loc_lower = (location or "").strip().lower()
    if not loc_lower:
        return True

    target_lowers = [loc.strip().lower() for loc in target_locations if loc.strip()]
    wants_remote = any("remote" in t for t in target_lowers)

    if work_type_hint == "remote" and wants_remote:
        return True

    for target in target_lowers:
        city_part = target.split(",")[0].strip()
        if city_part and city_part in loc_lower:
            return True
        for key, aliases in _CITY_ALIASES.items():
            if key in target:
                if key == "remote":
                    if "remote" in loc_lower:
                        return True
                elif any(alias in loc_lower for alias in aliases if len(alias) > 2):
                    return True

    if "united states" in loc_lower and "remote" in loc_lower and wants_remote:
        return True
    return False


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


def fetch_linkedin_candidates(
    role_query: str,
    location_query: str,
    posted_within: str,
    work_types: list[str],
    job_types: list[str],
    client: httpx.Client,
) -> list[RawCandidate]:
    """Query LinkedIn public guest search HTML endpoint using f_TPR freshness filter."""
    params: dict[str, str] = {
        "keywords": role_query,
        "location": location_query or "United States",
        "start": "0",
    }
    ftpr = LINKEDIN_FTPR.get(posted_within)
    if ftpr:
        params["f_TPR"] = ftpr
    wt_codes = []
    for wt in work_types:
        if wt == "onsite":
            wt_codes.append("1")
        elif wt == "remote":
            wt_codes.append("2")
        elif wt == "hybrid":
            wt_codes.append("3")
    if wt_codes and len(wt_codes) < 3:
        params["f_WT"] = ",".join(wt_codes)
    if job_types == ["full-time"]:
        params["f_JT"] = "F"
    elif job_types == ["contract"]:
        params["f_JT"] = "C"

    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    resp = client.get(url, params=params)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    cards = soup.find_all(["li", "div"], class_=re.compile(r"base-card|job-search-card"))
    seen_card_urls: set[str] = set()
    results: list[RawCandidate] = []

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
            # Date-only attributes (YYYY-MM-DD) lack hour precision; only parse when time-of-day is present
            if len(dt_attr) > 10 or posted_within == "7d":
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
        posted_at=rec.posted_at,
        work_type=rec.work_type,
        job_type=rec.job_type,
        work_auth=rec.work_auth,
        disposition=rec.disposition,
        application_status=rec.application_status,
        relevance_score=rec.relevance_score,
        created_at=rec.created_at,
    )


def run_batch_scrape(
    db: Session,
    session_rec: ScrapeSessionRecord,
    req: ScrapeBatchRequest,
    config_manager: ConfigManager,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> ScrapeBatchResult:
    """Pull postings across target roles and apply simultaneous inline filtering + permanent deduplication."""
    settings = config_manager.get_settings()
    all_tracks = config_manager.list_role_tracks()
    track_map = {t.id: t for t in all_tracks}

    posted_within = req.posted_within or settings.posted_within_default or "24h"
    selected_track_ids = req.role_tracks or settings.target_role_tracks or [t.id for t in all_tracks]
    selected_tracks = [track_map[tid] for tid in selected_track_ids if tid in track_map]
    target_locations = req.locations if req.locations is not None else settings.target_locations
    sources = req.sources or settings.scraper_sources
    boards = req.company_boards if req.company_boards is not None else settings.company_boards
    ref_now = now or datetime.now(timezone.utc)

    owns_client = client is None
    http_client = client or httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0)
    candidates: list[RawCandidate] = []
    source_notes: list[str] = []

    try:
        # 1. Company ATS boards (Greenhouse / Lever)
        for entry in boards:
            if ":" not in entry:
                continue
            provider, slug = entry.split(":", 1)
            provider = provider.strip().lower()
            slug = slug.strip()
            if not slug or provider not in sources:
                continue
            try:
                if provider == "greenhouse":
                    fetched = fetch_greenhouse_candidates(slug, http_client)[: req.max_per_source]
                    candidates.extend(fetched)
                elif provider == "lever":
                    fetched = fetch_lever_candidates(slug, http_client)[: req.max_per_source]
                    candidates.extend(fetched)
            except Exception as exc:
                source_notes.append(f"{entry}: {exc}")

        # 2. LinkedIn public guest search across target role tracks & locations
        if "linkedin" in sources:
            li_locations = target_locations[:4] if target_locations else ["United States"]
            for track in selected_tracks[:4]:
                clean_query = re.sub(r"\([^)]*\)", "", track.display_name).strip()
                for loc in li_locations:
                    for attempt in range(2 if owns_client else 1):
                        try:
                            if owns_client:
                                time.sleep(0.85 if attempt == 0 else 2.2)
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

        # 3. Simultaneous inline two-stage filtering loop
        scanned_count = len(candidates)
        saved_jobs: list[JobPostingResponse] = []
        filtered_samples: list[FilteredJobSample] = []
        filter_breakdown: dict[str, int] = {}
        duplicate_skipped_count = 0
        seen_in_batch_urls: set[str] = set()
        seen_in_batch_cross_fps: set[tuple[str, str]] = set()

        def _drop(cand: RawCandidate, reason: str, fp: str, u_hash: str | None, *, persist_seen: bool) -> None:
            filter_breakdown[reason] = filter_breakdown.get(reason, 0) + 1
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

        for cand in candidates:
            canon_u = canonicalize_url(cand.url)
            u_hash = hash_url(canon_u)
            fp = make_content_fingerprint(cand.company, cand.title, cand.location)

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
                continue

            # Gate 1A: Permanent seen/discarded ledger check BEFORE full JD fetch
            already_seen, seen_reason = is_job_already_seen(db, u_hash, fp, cand.source)
            if already_seen:
                duplicate_skipped_count += 1
                reason_key = seen_reason or "already_seen"
                filter_breakdown[reason_key] = filter_breakdown.get(reason_key, 0) + 1
                continue

            # Gate 1B: Freshness check before full JD fetch
            if not is_within_freshness(cand.posted_at, posted_within, ref_now):
                _drop(cand, "stale_outside_window", fp, u_hash, persist_seen=False)
                continue

            # Gate 1C: Title blocklist & target role track match
            if _evaluate_title_blocklist(cand.title, settings.title_blocklist):
                _drop(cand, "blocked_title", fp, u_hash, persist_seen=True)
                continue

            matched_track = _match_target_role(cand.title, selected_tracks)
            if selected_tracks and matched_track is None:
                _drop(cand, "role_mismatch", fp, u_hash, persist_seen=True)
                continue

            # Gate 1D: City / Remote target location match
            if cand.location and not _matches_target_location(
                cand.location, target_locations, cand.work_type_hint
            ):
                _drop(cand, "location_mismatch", fp, u_hash, persist_seen=True)
                continue

            # Fetch full JD text if only a summary card was available
            full_text = cand.raw_text or ""
            if not full_text:
                fetch_target = cand.detail_url or canon_u or cand.url
                if fetch_target:
                    last_exc: Exception | None = None
                    for attempt in range(3 if (owns_client and "linkedin" in cand.source) else 1):
                        try:
                            if owns_client and "linkedin" in cand.source:
                                time.sleep(1.1 if attempt == 0 else 2.5 * attempt)
                            scraped = fetch_job_posting(url=fetch_target, client=http_client)
                            full_text = scraped.raw_text
                            last_exc = None
                            break
                        except Exception as exc:
                            last_exc = exc
                            if "429" not in str(exc):
                                break
                    if last_exc is not None:
                        _drop(cand, "fetch_failed", fp, u_hash, persist_seen=False)
                        source_notes.append(f"detail {cand.company} ({cand.title}): {last_exc}")
                        continue
            if not full_text.strip():
                _drop(cand, "empty_jd", fp, u_hash, persist_seen=False)
                continue

            # Gate 2: Full JD deterministic analysis & filter rules
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
                _drop(cand, f"work_type:{analysis.work_type}", fp, u_hash, persist_seen=True)
                continue

            # Employment type check (full-time vs contract)
            if settings.job_types and analysis.job_type not in settings.job_types:
                _drop(cand, f"job_type:{analysis.job_type}", fp, u_hash, persist_seen=True)
                continue

            # Work authorization / H-1B check
            if settings.work_authorization == "h1b" and analysis.work_auth == "no_sponsorship":
                _drop(cand, "no_h1b_sponsorship", fp, u_hash, persist_seen=True)
                continue

            # Compensation floor ONLY when explicit USD salary is stated; omitted salary is KEPT
            sal = analysis.salary
            if sal.min_amount is not None and sal.currency == "USD":
                top_val = sal.max_amount if sal.max_amount is not None else sal.min_amount
                if (
                    sal.period == "year"
                    and settings.target_salary_min is not None
                    and top_val < settings.target_salary_min
                ):
                    _drop(cand, "below_min_salary", fp, u_hash, persist_seen=True)
                    continue
                if (
                    sal.period == "hour"
                    and settings.min_hourly_rate is not None
                    and top_val < settings.min_hourly_rate
                ):
                    _drop(cand, "below_min_hourly", fp, u_hash, persist_seen=True)
                    continue

            # Years-of-experience guard when explicit floor is wildly outside senior band
            yoe = analysis.yoe
            if yoe.min_years is not None and yoe.min_years > settings.target_yoe_max + 2:
                _drop(cand, "yoe_too_high", fp, u_hash, persist_seen=True)
                continue
            if (
                yoe.max_years is not None
                and yoe.max_years < max(0, settings.target_yoe_min - 2)
            ):
                _drop(cand, "yoe_too_low", fp, u_hash, persist_seen=True)
                continue

            # Initial relevance score against best available base resume
            rel_score = compute_initial_relevance(db, analysis, settings, config_manager)
            if settings.min_relevance_score > 0 and rel_score < settings.min_relevance_score:
                _drop(cand, "below_min_relevance", fp, u_hash, persist_seen=True)
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
        filtered_total = sum(filter_breakdown.values())
        session_rec.posted_within = posted_within
        session_rec.scanned_count += scanned_count
        session_rec.saved_count += len(saved_jobs)
        session_rec.filtered_count += filtered_total

        prev_breakdown = json.loads(session_rec.filter_breakdown_json or "{}")
        for k, v in filter_breakdown.items():
            prev_breakdown[k] = prev_breakdown.get(k, 0) + v
        session_rec.filter_breakdown_json = json.dumps(prev_breakdown)

        prev_notes = json.loads(session_rec.source_notes_json or "[]")
        session_rec.source_notes_json = json.dumps((prev_notes + source_notes)[-20:])

        db.commit()
        for j in saved_jobs:
            # Ensure created_at / DB fields stay fresh
            pass

        return ScrapeBatchResult(
            session_id=session_rec.id,
            posted_within=posted_within,
            scanned_count=scanned_count,
            saved_count=len(saved_jobs),
            filtered_count=filtered_total,
            duplicate_skipped_count=duplicate_skipped_count,
            filter_breakdown=filter_breakdown,
            source_notes=source_notes,
            saved_jobs=saved_jobs,
            filtered_samples=filtered_samples,
        )
    finally:
        if owns_client:
            http_client.close()
