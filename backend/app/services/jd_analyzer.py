"""Deterministic job description analyzer: weighted skills, salary, YoE, location, expectations."""

from __future__ import annotations

import re

from backend.app.schemas.config import AppSettings, RoleTrackConfig
from backend.app.schemas.job import JobAnalysis, SalaryInfo, WeightedSkill, YoeInfo
from backend.app.services.label_formatter import format_skill_name
from backend.app.services.skill_enrichment import enrich_job_weighted_skills, is_non_work_jd_line

TIER_LABELS = {
    "core_must_have": "Must-Have",
    "important_systems": "Important",
    "senior_leadership": "Senior Signal",
    "bonus_nice_to_have": "Nice-to-Have",
}

REQUIRED_SECTION_MARKERS = (
    "minimum qualifications",
    "required qualifications",
    "basic qualifications",
    "requirements",
    "what we're looking for",
    "what you bring",
    "must have",
    "skills required",
)

PREFERRED_SECTION_MARKERS = (
    "preferred qualifications",
    "nice to have",
    "bonus",
    "plus",
)

RESPONSIBILITY_SECTION_MARKERS = (
    "responsibilities",
    "what you'll do",
    "what you will do",
    "in this role",
    "role overview",
    "about the role",
)

SENIOR_SIGNALS = (
    "system design",
    "architecture",
    "distributed",
    "scalability",
    "latency",
    "throughput",
    "ownership",
    "mentorship",
    "cross-functional",
    "production",
    "reliability",
    "sla",
    "slo",
)

CURRENCY_SYMBOL_MAP = {
    "$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "CAD": "CAD",
    "C$": "CAD",
}


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    escaped = re.escape(keyword.lower())
    return re.compile(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", re.IGNORECASE)


def _parse_money_token(num_str: str, suffix: str | None) -> int:
    value = float(num_str.replace(",", ""))
    if suffix and suffix.lower() == "k":
        value *= 1000
    return int(round(value))


def _normalize_currency(raw_curr: str | None) -> str:
    if not raw_curr:
        return "USD"
    return CURRENCY_SYMBOL_MAP.get(raw_curr.strip().upper(), "USD")


def extract_salary(
    text: str,
    target_salary_min: int | None = None,
) -> SalaryInfo:
    """Extract listed annual salary range (USD or foreign currencies) and check USD target."""
    range_re = re.compile(
        r"(?P<curr>C\$|\$|€|£|USD\s*|CAD\s*|EUR\s*|GBP\s*)?"
        r"(?P<min>\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?)\s*(?P<min_k>k)?\s*"
        r"(?:-|–|—|to)\s*"
        r"(?P<curr2>C\$|\$|€|£|USD\s*|CAD\s*|EUR\s*|GBP\s*)?"
        r"(?P<max>\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?)\s*(?P<max_k>k)?",
        re.IGNORECASE,
    )

    for match in range_re.finditer(text):
        has_currency = bool(match.group("curr") or match.group("curr2"))
        if not has_currency:
            continue
        low = _parse_money_token(match.group("min"), match.group("min_k") or match.group("max_k"))
        high = _parse_money_token(match.group("max"), match.group("max_k"))
        if low < 35_000 or high < low or high > 2_000_000:
            continue
        currency = _normalize_currency(match.group("curr") or match.group("curr2"))
        meets = (
            None
            if (target_salary_min is None or currency != "USD")
            else (high >= target_salary_min)
        )
        return SalaryInfo(
            min_amount=low,
            max_amount=high,
            currency=currency,
            period="year",
            raw_snippet=match.group(0).strip(),
            meets_target=meets,
        )

    single_re = re.compile(
        r"(?:salary|compensation|pay|ote|base)[^.\n]{0,40}?"
        r"(?P<curr>C\$|\$|€|£|USD\s*|CAD\s*|EUR\s*|GBP\s*)(?P<amt>\d{2,3}(?:,\d{3})+|\d{2,3})\s*(?P<k>k)?",
        re.IGNORECASE,
    )
    single_match = single_re.search(text)
    if single_match:
        amount = _parse_money_token(single_match.group("amt"), single_match.group("k"))
        if 35_000 <= amount <= 2_000_000:
            currency = _normalize_currency(single_match.group("curr"))
            meets = (
                None
                if (target_salary_min is None or currency != "USD")
                else (amount >= target_salary_min)
            )
            return SalaryInfo(
                min_amount=amount,
                max_amount=amount,
                currency=currency,
                period="year",
                raw_snippet=single_match.group(0).strip(),
                meets_target=meets,
            )

    hourly_range_re = re.compile(
        r"(?P<curr>C\$|\$|€|£|USD\s*|CAD\s*|EUR\s*|GBP\s*)\s*(?P<min>\d{2,3}(?:\.\d{1,2})?)"
        r"\s*(?:-|to|–|—)\s*"
        r"(?P<curr2>C\$|\$|€|£|USD\s*|CAD\s*|EUR\s*|GBP\s*)?\s*(?P<max>\d{2,3}(?:\.\d{1,2})?)"
        r"\s*(?:/\s*h(?:ou)?r|per\s+h(?:ou)?r|hourly)",
        re.IGNORECASE,
    )
    hourly_match = hourly_range_re.search(text)
    if hourly_match:
        low_hr = int(round(float(hourly_match.group("min"))))
        high_hr = int(round(float(hourly_match.group("max"))))
        if 15 <= low_hr <= high_hr <= 500:
            currency = _normalize_currency(hourly_match.group("curr") or hourly_match.group("curr2"))
            return SalaryInfo(
                min_amount=low_hr,
                max_amount=high_hr,
                currency=currency,
                period="hour",
                raw_snippet=hourly_match.group(0).strip(),
                meets_target=None,
            )

    hourly_single_re = re.compile(
        r"(?P<curr>C\$|\$|€|£|USD\s*|CAD\s*|EUR\s*|GBP\s*)\s*(?P<amt>\d{2,3}(?:\.\d{1,2})?)"
        r"\s*(?:/\s*h(?:ou)?r|per\s+h(?:ou)?r|hourly)",
        re.IGNORECASE,
    )
    hourly_single = hourly_single_re.search(text)
    if hourly_single:
        amt_hr = int(round(float(hourly_single.group("amt"))))
        if 15 <= amt_hr <= 500:
            currency = _normalize_currency(hourly_single.group("curr"))
            return SalaryInfo(
                min_amount=amt_hr,
                max_amount=amt_hr,
                currency=currency,
                period="hour",
                raw_snippet=hourly_single.group(0).strip(),
                meets_target=None,
            )

    return SalaryInfo(currency="USD")


_NO_SPONSORSHIP_SIGNALS = (
    "no h1b",
    "no h-1b",
    "no visa",
    "no sponsorship",
    "not sponsor",
    "cannot sponsor",
    "unable to sponsor",
    "will not sponsor",
    "does not sponsor",
    "sponsorship not available",
    "sponsorship is not available",
    "without sponsorship",
    "us citizens only",
    "u.s. citizens only",
    "citizens only",
    "green card only",
    "permanent residents only",
    "must be a us citizen",
    "must be a u.s. citizen",
    "active clearance required",
    "top secret clearance",
    "no opt",
    "no cpt",
)

_H1B_OK_SIGNALS = (
    "visa sponsorship",
    "h1b sponsorship",
    "h-1b sponsorship",
    "sponsorship available",
    "will sponsor",
    "h1b",
    "h-1b",
)

_CONTRACT_SIGNALS = (
    "c2c",
    "corp-to-corp",
    "corp to corp",
    "1099",
    "w2 contract",
    "w-2 contract",
    "contract role",
    "contract position",
    "contract-to-hire",
    "contract to hire",
    "hourly rate",
    "independent contractor",
)

_FULLTIME_OVERRIDE_SIGNALS = (
    "full-time",
    "full time",
    "fte",
    "salaried position",
    "permanent role",
)


def extract_work_type(text: str, location: str = "") -> str:
    """Classify arrangement as remote, hybrid, onsite, or unspecified."""
    combined = f"{location}\n{text[:1500]}".lower()
    if re.search(r"\bhybrid\b", combined):
        return "hybrid"
    if re.search(r"\b(remote|work from home|wfh|distributed team)\b", combined):
        return "remote"
    if re.search(r"\b(on-?site|in-?office|in person)\b", combined):
        return "onsite"
    return "unspecified"


def extract_job_type(text: str, title: str = "") -> str:
    """Classify employment type as contract vs full-time."""
    combined = f"{title}\n{text[:2500]}".lower()
    has_contract = any(sig in combined for sig in _CONTRACT_SIGNALS) or bool(
        re.search(r"\b\d+\s*(?:month|mo)\s+contract\b", combined)
    )
    has_ft = any(sig in combined for sig in _FULLTIME_OVERRIDE_SIGNALS)
    if has_contract and not has_ft:
        return "contract"
    if "contract" in title.lower():
        return "contract"
    return "full-time"


def extract_work_auth(text: str) -> str:
    """Detect explicit visa/H-1B sponsorship stance in a job description."""
    lowered = text.lower()
    if any(sig in lowered for sig in _NO_SPONSORSHIP_SIGNALS):
        return "no_sponsorship"
    if any(sig in lowered for sig in _H1B_OK_SIGNALS):
        return "h1b_ok"
    return "unspecified"


def extract_yoe(
    text: str,
    target_min: int | None = 4,
    target_max: int | None = 8,
) -> YoeInfo:
    """Extract required years of experience and evaluate overlap with optional YoE bounds."""
    range_match = re.search(
        r"(\d{1,2})\s*(?:-|–|to)\s*(\d{1,2})\s*\+?\s*years?(?:\s+of)?\s+(?:[a-z\s]{0,25})?experience",
        text,
        re.IGNORECASE,
    )
    if range_match:
        low, high = int(range_match.group(1)), int(range_match.group(2))
        fits_max = True if target_max is None else (low <= target_max)
        fits_min = True if target_min is None else (high >= target_min)
        return YoeInfo(
            min_years=low,
            max_years=high,
            raw_snippet=range_match.group(0).strip(),
            fits_target_range=fits_max and fits_min,
        )

    min_match = re.search(
        r"(?:at\s+least|minimum(?:\s+of)?|\b)(\d{1,2})\s*\+?\s*years?(?:\s+of)?\s+(?:[a-z\s]{0,30})?experience",
        text,
        re.IGNORECASE,
    )
    if min_match:
        low = int(min_match.group(1))
        fits_max = True if target_max is None else (low <= target_max)
        fits_min = True if target_min is None else (low >= target_min - 1)
        return YoeInfo(
            min_years=low,
            max_years=None,
            raw_snippet=min_match.group(0).strip(),
            fits_target_range=fits_max and fits_min,
        )

    return YoeInfo()


def extract_location(raw_text: str, scraped_location: str | None, location_override: str | None) -> str:
    """Resolve job location from override, scraper metadata, or 'Location:' line in pasted text."""
    if location_override and location_override.strip():
        return location_override.strip()
    if scraped_location and scraped_location.strip():
        return scraped_location.strip()

    for line in raw_text.splitlines()[:10]:
        m = re.match(r"^(?:location|office|city)\s*:\s*(.+)$", line.strip(), re.IGNORECASE)
        if m:
            return m.group(1).strip()[:120]
    return ""


def _split_jd_sections(text: str) -> dict[str, str]:
    buckets: dict[str, list[str]] = {
        "required": [],
        "preferred": [],
        "responsibilities": [],
        "general": [],
    }
    current = "general"
    for line in text.splitlines():
        clean = line.strip()
        lower = clean.lower().rstrip(":")
        if len(clean) <= 80:
            if any(m in lower for m in PREFERRED_SECTION_MARKERS):
                current = "preferred"
                continue
            if any(m in lower for m in REQUIRED_SECTION_MARKERS):
                current = "required"
                continue
            if any(m in lower for m in RESPONSIBILITY_SECTION_MARKERS):
                current = "responsibilities"
                continue
        buckets[current].append(clean)
    return {k: "\n".join(v) for k, v in buckets.items()}


def infer_header_metadata(
    raw_text: str,
    scraped_title: str | None,
    scraped_company: str | None,
    company_override: str | None,
    title_override: str | None,
) -> tuple[str, str]:
    company = (company_override or scraped_company or "").strip()
    title = (title_override or scraped_title or "").strip()

    first_lines = [line.strip() for line in raw_text.splitlines() if line.strip()][:5]
    if not title and first_lines:
        title = first_lines[0][:120]
    if not company:
        for line in first_lines[:4]:
            m = re.search(r"^(?:company|organization)\s*:\s*(.+)$", line, re.IGNORECASE)
            if m:
                company = m.group(1).strip()
                break
        if not company and len(first_lines) >= 2 and "@" in first_lines[0]:
            company = first_lines[0].split("@", 1)[1].strip()
    return company or "Unknown Company", title or "Untitled Role"


def _extract_expected_work(sections: dict[str, str], raw_text: str) -> list[str]:
    source = sections["responsibilities"] or sections["required"] or raw_text
    expectations: list[str] = []
    for line in source.splitlines():
        cleaned = re.sub(r"^[\-\*•\u2022\d\.)\s]+", "", line).strip()
        if 25 <= len(cleaned) <= 220 and not is_non_work_jd_line(cleaned):
            expectations.append(cleaned)
        if len(expectations) >= 8:
            break
    return expectations


def analyze_job_posting(
    raw_text: str,
    role_track: RoleTrackConfig,
    settings: AppSettings,
    scraped_title: str | None = None,
    scraped_company: str | None = None,
    scraped_location: str | None = None,
    company_override: str | None = None,
    title_override: str | None = None,
    location_override: str | None = None,
) -> JobAnalysis:
    """Analyze JD text against the active role track and Senior 4-8 YoE settings."""
    company, title = infer_header_metadata(
        raw_text, scraped_title, scraped_company, company_override, title_override
    )
    location = extract_location(raw_text, scraped_location, location_override)
    sections = _split_jd_sections(raw_text)
    salary = extract_salary(raw_text, target_salary_min=settings.target_salary_min)
    yoe = extract_yoe(raw_text, settings.target_yoe_min, settings.target_yoe_max)

    tier_specs = [
        ("core_must_have", role_track.weights.core_must_have, role_track.keywords.core_must_have),
        (
            "important_systems",
            role_track.weights.important_systems,
            role_track.keywords.important_systems,
        ),
        (
            "senior_leadership",
            role_track.weights.senior_leadership,
            role_track.keywords.senior_leadership,
        ),
        (
            "bonus_nice_to_have",
            role_track.weights.bonus_nice_to_have,
            role_track.keywords.bonus_nice_to_have,
        ),
    ]

    seen_keywords: set[str] = set()
    weighted_skills: list[WeightedSkill] = []
    required_blob = sections["required"]

    for tier, base_weight, keywords in tier_specs:
        for kw in keywords:
            norm = kw.strip().lower()
            if not norm or norm in seen_keywords:
                continue
            pattern = _keyword_pattern(norm)
            matches = pattern.findall(raw_text)
            if not matches:
                continue
            seen_keywords.add(norm)
            in_required = bool(required_blob and pattern.search(required_blob))
            mentions = len(matches)
            effective_weight = round(
                base_weight * (1.3 if in_required else 1.0) * (1.0 + min(mentions - 1, 3) * 0.15),
                2,
            )
            weighted_skills.append(
                WeightedSkill(
                    keyword=format_skill_name(kw),
                    tier=tier,  # type: ignore[arg-type]
                    priority_label=TIER_LABELS[tier],
                    weight=effective_weight,
                    jd_mentions=mentions,
                    in_required_section=in_required,
                )
            )

    weighted_skills = enrich_job_weighted_skills(raw_text, weighted_skills)
    detected_signals = [sig for sig in SENIOR_SIGNALS if _keyword_pattern(sig).search(raw_text)]
    expected_work = _extract_expected_work(sections, raw_text)
    work_type = extract_work_type(raw_text, location)
    job_type = extract_job_type(raw_text, title)
    work_auth = extract_work_auth(raw_text)

    return JobAnalysis(
        company=company,
        title=title,
        location=location,
        role_track=role_track.id,
        salary=salary,
        yoe=yoe,
        weighted_skills=weighted_skills,
        expected_work=expected_work,
        detected_signals=detected_signals,
        work_type=work_type,
        job_type=job_type,
        work_auth=work_auth,
    )
