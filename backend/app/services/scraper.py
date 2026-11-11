"""Job posting URL scraper with JSON-LD, ATS board extraction, and paste fallback."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class ScrapeError(RuntimeError):
    """Raised when a job URL cannot be fetched or requires manual JD paste."""


@dataclass(frozen=True)
class ScrapedJobContent:
    """Normalized raw content extracted from a job posting URL or pasted text."""

    url: str | None
    title: str | None
    company: str | None
    location: str | None
    raw_text: str


def _clean_html_fragment(value: str) -> str:
    if "<" not in value:
        return re.sub(r"\s+", " ", value).strip()
    soup = BeautifulSoup(value, "html.parser")
    lines = [line.strip() for line in soup.get_text("\n").splitlines()]
    return "\n".join(line for line in lines if line)


def _extract_json_ld_job(soup: BeautifulSoup) -> dict[str, Any] | None:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw_json = script.string or script.get_text()
        if not raw_json or not raw_json.strip():
            continue
        try:
            payload = json.loads(raw_json)
        except json.JSONDecodeError:
            continue
        candidates = payload if isinstance(payload, list) else [payload]
        for item in candidates:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "JobPosting":
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                for node in graph:
                    if isinstance(node, dict) and node.get("@type") == "JobPosting":
                        return node
    return None


def _extract_location_from_json_ld(job_ld: dict[str, Any]) -> str | None:
    loc = job_ld.get("jobLocation")
    if isinstance(loc, list) and loc:
        loc = loc[0]
    if isinstance(loc, dict):
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [
                str(addr.get("addressLocality") or "").strip(),
                str(addr.get("addressRegion") or "").strip(),
                str(addr.get("addressCountry") or "").strip(),
            ]
            joined = ", ".join(p for p in parts if p)
            if joined:
                return joined
    if job_ld.get("jobLocationType") == "TELECOMMUTE":
        return "Remote"
    return None


def _extract_company_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path_parts = [p for p in parsed.path.split("/") if p]
    if ("greenhouse.io" in host or "lever.co" in host or "ashbyhq.com" in host) and path_parts:
        return path_parts[0].replace("-", " ").title()
    return None


def _infer_meta_content(soup: BeautifulSoup, *names: str) -> str | None:
    for name in names:
        tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
        if tag and tag.get("content"):
            text = str(tag["content"]).strip()
            if text:
                return text
    return None


def _extract_main_text(soup: BeautifulSoup) -> str:
    for noisy in soup(["script", "style", "noscript", "svg", "nav", "footer", "header"]):
        noisy.decompose()

    # Check high-signal ATS / job-board containers first (choosing richest match, not tiny modals)
    for selector_cls in ("show-more-less-html__markup", "description__text"):
        li_box = soup.find(class_=selector_cls)
        if li_box and len(li_box.get_text(" ", strip=True)) > 150:
            lines = [line.strip() for line in li_box.get_text("\n").splitlines()]
            return "\n".join(line for line in lines if line)

    candidates = soup.find_all(
        attrs={"class": re.compile(r"(posting|job[-_]?desc|description__text|job-description)", re.I)}
    )
    best_candidate = max(
        candidates,
        key=lambda el: len(el.get_text(" ", strip=True)),
        default=None,
    )
    target = (
        (best_candidate if best_candidate and len(best_candidate.get_text(" ", strip=True)) > 120 else None)
        or soup.find("main")
        or soup.find("article")
        or soup.body
        or soup
    )
    lines = [line.strip() for line in target.get_text("\n").splitlines()]
    compact = [line for line in lines if line]
    return "\n".join(compact)


def parse_job_html(html: str, url: str) -> ScrapedJobContent:
    """Extract job metadata and clean text from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    json_ld = _extract_json_ld_job(soup)

    title: str | None = None
    company: str | None = None
    location: str | None = None
    description_text = ""

    if json_ld:
        title = str(json_ld.get("title") or "").strip() or None
        org = json_ld.get("hiringOrganization")
        if isinstance(org, dict):
            company = str(org.get("name") or "").strip() or None
        location = _extract_location_from_json_ld(json_ld)
        raw_desc = str(json_ld.get("description") or "").strip()
        if raw_desc:
            description_text = _clean_html_fragment(raw_desc)

    if not title:
        h1 = soup.find("h1")
        title = (h1.get_text(" ", strip=True) if h1 else None) or _infer_meta_content(
            soup, "og:title", "twitter:title"
        )
        if not title and soup.title:
            title = soup.title.get_text(" ", strip=True)

    if not company:
        company = _infer_meta_content(soup, "og:site_name") or _extract_company_from_url(url)

    body_text = _extract_main_text(soup)
    combined_text = description_text if len(description_text) >= len(body_text) * 0.6 else body_text
    if description_text and description_text not in combined_text:
        combined_text = f"{description_text}\n\n{body_text}".strip()

    if len(combined_text.strip()) < 60:
        raise ScrapeError(
            "Fetched page had too little job text (likely JS-rendered or gated). "
            "Please paste the job description text directly."
        )

    return ScrapedJobContent(
        url=url,
        title=title,
        company=company,
        location=location,
        raw_text=combined_text,
    )


def fetch_job_posting(
    url: str | None = None,
    raw_text: str | None = None,
    client: httpx.Client | None = None,
) -> ScrapedJobContent:
    """Return normalized job text from pasted text or by fetching and parsing URL."""
    if raw_text and raw_text.strip():
        return ScrapedJobContent(
            url=url.strip() if url else None,
            title=None,
            company=None,
            location=None,
            raw_text=raw_text.strip(),
        )

    if not url or not url.strip():
        raise ScrapeError("Either a job URL or pasted job text is required.")

    clean_url = url.strip()
    owns_client = client is None
    http_client = client or httpx.Client(headers=DEFAULT_HEADERS, follow_redirects=True, timeout=15.0)
    try:
        response = http_client.get(clean_url)
    except httpx.HTTPError as exc:
        raise ScrapeError(
            f"Could not fetch URL ({exc}). Please paste the job description text directly."
        ) from exc
    finally:
        if owns_client:
            http_client.close()

    if response.status_code in (401, 403, 429):
        raise ScrapeError(
            f"Site returned HTTP {response.status_code} (anti-bot or login wall). "
            "Please paste the job description text directly."
        )
    if response.status_code >= 400:
        raise ScrapeError(f"Failed to fetch job URL (HTTP {response.status_code}).")

    content_type = response.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        try:
            data = response.json()
            title = data.get("title")
            location_obj = data.get("location")
            location = (
                location_obj.get("name")
                if isinstance(location_obj, dict)
                else (str(location_obj) if location_obj else None)
            )
            desc = _clean_html_fragment(str(data.get("content") or data.get("description") or ""))
            if desc:
                return ScrapedJobContent(
                    url=clean_url,
                    title=title,
                    company=_extract_company_from_url(clean_url),
                    location=location,
                    raw_text=desc,
                )
        except Exception:
            pass

    return parse_job_html(response.text, clean_url)
