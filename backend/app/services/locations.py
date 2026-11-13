"""Curated US tech city catalog, Top 20 tech hubs, and strict location matching."""

from __future__ import annotations

import re

TOP_20_US_LOCATIONS: list[str] = [
    "Seattle, WA",
    "San Francisco, CA",
    "New York, NY",
    "San Jose, CA",
    "Austin, TX",
    "San Diego, CA",
    "Boston, MA",
    "Los Angeles, CA",
    "Mountain View, CA",
    "Palo Alto, CA",
    "Sunnyvale, CA",
    "Bellevue, WA",
    "Redmond, WA",
    "Chicago, IL",
    "Denver, CO",
    "Atlanta, GA",
    "Washington, DC",
    "Dallas, TX",
    "Raleigh, NC",
    "Remote",
]

OTHER_US_TECH_CITIES: list[str] = [
    "Albany, NY",
    "Albuquerque, NM",
    "Ann Arbor, MI",
    "Arlington, VA",
    "Baltimore, MD",
    "Baton Rouge, LA",
    "Bentonville, AR",
    "Berkeley, CA",
    "Bethesda, MD",
    "Birmingham, AL",
    "Boise, ID",
    "Boulder, CO",
    "Brooklyn, NY",
    "Broomfield, CO",
    "Buffalo, NY",
    "Burbank, CA",
    "Cambridge, MA",
    "Carlsbad, CA",
    "Cary, NC",
    "Chandler, AZ",
    "Charleston, SC",
    "Charlotte, NC",
    "Chattanooga, TN",
    "Cincinnati, OH",
    "Cleveland, OH",
    "Colorado Springs, CO",
    "Columbus, OH",
    "Costa Mesa, CA",
    "Culver City, CA",
    "Cupertino, CA",
    "Des Moines, IA",
    "Detroit, MI",
    "Durham, NC",
    "El Segundo, CA",
    "Folsom, CA",
    "Fort Worth, TX",
    "Fremont, CA",
    "Frisco, TX",
    "Grand Rapids, MI",
    "Hartford, CT",
    "Herndon, VA",
    "Hoboken, NJ",
    "Honolulu, HI",
    "Houston, TX",
    "Huntsville, AL",
    "Indianapolis, IN",
    "Irvine, CA",
    "Irving, TX",
    "Jacksonville, FL",
    "Jersey City, NJ",
    "Kansas City, MO",
    "Kirkland, WA",
    "Knoxville, TN",
    "La Jolla, CA",
    "Las Vegas, NV",
    "Lehi, UT",
    "Lexington, KY",
    "Lincoln, NE",
    "Louisville, KY",
    "Madison, WI",
    "McLean, VA",
    "Menlo Park, CA",
    "Miami, FL",
    "Milwaukee, WI",
    "Minneapolis, MN",
    "Nashville, TN",
    "New Haven, CT",
    "New Orleans, LA",
    "Newark, NJ",
    "Newport Beach, CA",
    "Oakland, CA",
    "Oklahoma City, OK",
    "Omaha, NE",
    "Orlando, FL",
    "Pasadena, CA",
    "Philadelphia, PA",
    "Phoenix, AZ",
    "Pittsburgh, PA",
    "Plano, TX",
    "Playa Vista, CA",
    "Pleasanton, CA",
    "Portland, OR",
    "Princeton, NJ",
    "Provo, UT",
    "Redwood City, CA",
    "Reston, VA",
    "Richmond, VA",
    "Rochester, NY",
    "Sacramento, CA",
    "Salt Lake City, UT",
    "San Antonio, TX",
    "San Mateo, CA",
    "Santa Barbara, CA",
    "Santa Clara, CA",
    "Santa Monica, CA",
    "Scottsdale, AZ",
    "Somerville, MA",
    "South San Francisco, CA",
    "St. Louis, MO",
    "Stamford, CT",
    "Tampa, FL",
    "Tempe, AZ",
    "Tucson, AZ",
    "Tulsa, OK",
    "Tysons, VA",
    "Waltham, MA",
    "Wilmington, DE",
]

ALL_US_TECH_CITIES: list[str] = TOP_20_US_LOCATIONS + OTHER_US_TECH_CITIES

US_STATE_ABBREVS: set[str] = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
    "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
    "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
    "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
    "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
    "dc",
}

US_STATE_NAMES: set[str] = {
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania", "rhode island",
    "south carolina", "south dakota", "tennessee", "texas", "utah", "vermont",
    "virginia", "washington", "west virginia", "wisconsin", "wyoming",
    "district of columbia", "united states", "u.s.", "usa",
}

NON_US_MARKERS: tuple[str, ...] = (
    "london", "united kingdom", "england", "scotland", "edinburgh", "manchester", "belfast", "glasgow",
    "cambridge, uk", "oxford, uk", "ireland", "dublin", "canada", "toronto",
    "vancouver", "montreal", "ottawa", "waterloo", "ontario", "quebec", "british columbia", "alberta",
    "germany", "berlin", "munich", "hamburg", "frankfurt",
    "france", "paris", "lyon", "netherlands", "amsterdam", "rotterdam",
    "spain", "madrid", "barcelona", "portugal", "lisbon", "porto",
    "italy", "milan", "rome", "austria", "vienna", "belgium", "brussels",
    "poland", "warsaw", "krakow", "wroclaw", "romania", "bucharest", "czech", "prague",
    "india", "bengaluru", "bangalore", "hyderabad", "mumbai", "pune", "delhi", "gurgaon", "noida",
    "chennai", "kolkata", "ahmedabad", "karnataka", "maharashtra", "telangana", "tamil nadu",
    "singapore", "japan", "tokyo", "osaka", "korea", "seoul", "china", "beijing", "shanghai", "taiwan",
    "philippines", "manila", "vietnam", "australia", "sydney", "melbourne", "new zealand", "auckland",
    "brazil", "sao paulo", "mexico", "mexico city", "colombia", "bogota", "argentina", "buenos aires", "chile",
    "israel", "tel aviv", "united arab emirates", "dubai", "uae",
    "switzerland", "zurich", "geneva", "sweden", "stockholm", "norway", "oslo", "denmark", "copenhagen",
    "finland", "helsinki", "emea", "apac", "latam", "europe", "uk", "global remote", "worldwide", "outside us",
    "outside the us", "non-us", "international",
)

# Unambiguous foreign 2-letter country / Canadian province codes (never collide with US state codes)
_FOREIGN_COUNTRY_OR_PROVINCE_ABBRS: set[str] = {
    "uk", "gb", "fr", "es", "it", "nl", "pl", "ie", "ch", "se", "no", "dk", "fi",
    "au", "nz", "sg", "jp", "kr", "cn", "tw", "br", "mx", "cl", "ae", "pt", "at",
    "be", "ro", "cz", "on", "bc", "qc", "ab", "ua", "tr", "ph", "vn", "za",
}

CITY_ALIASES: dict[str, tuple[str, ...]] = {
    "seattle": ("seattle", "bellevue", "redmond", "kirkland", "greater seattle", "bothell", "renton"),
    "san francisco": (
        "san francisco",
        "sf",
        "bay area",
        "oakland",
        "palo alto",
        "menlo park",
        "mountain view",
        "sunnyvale",
        "san jose",
        "south san francisco",
        "san mateo",
        "redwood city",
        "fremont",
        "santa clara",
        "cupertino",
        "berkeley",
    ),
    "san jose": ("san jose", "santa clara", "sunnyvale", "mountain view", "cupertino", "milpitas", "silicon valley"),
    "san diego": ("san diego", "la jolla", "carlsbad", "sorrento valley"),
    "new york": ("new york", "nyc", "manhattan", "brooklyn", "jersey city", "hoboken", "long island city"),
    "austin": ("austin", "round rock"),
    "boston": ("boston", "cambridge", "somerville", "waltham", "greater boston"),
    "los angeles": ("los angeles", "santa monica", "culver city", "playa vista", "pasadena", "venice", "el segundo", "burbank"),
    "mountain view": ("mountain view",),
    "palo alto": ("palo alto", "menlo park", "redwood city", "stanford"),
    "sunnyvale": ("sunnyvale", "santa clara", "mountain view"),
    "bellevue": ("bellevue", "seattle", "redmond", "kirkland"),
    "redmond": ("redmond", "bellevue", "seattle", "kirkland"),
    "chicago": ("chicago", "greater chicago", "evanston"),
    "denver": ("denver", "boulder", "broomfield"),
    "atlanta": ("atlanta", "alpharetta"),
    "washington": ("washington, dc", "washington dc", "arlington", "mclean", "reston", "tysons", "bethesda", "northern virginia"),
    "dallas": ("dallas", "plano", "irving", "frisco", "fort worth"),
    "raleigh": ("raleigh", "durham", "cary", "research triangle"),
    "salt lake city": ("salt lake city", "lehi", "draper", "provo"),
    "phoenix": ("phoenix", "scottsdale", "tempe", "chandler"),
    "portland": ("portland, or", "beaverton", "hillsboro"),
    "remote": ("remote", "distributed", "work from home", "anywhere in us", "united states (remote)"),
}

_ALL_CITY_PREFIXES: set[str] = {c.split(",")[0].strip().lower() for c in ALL_US_TECH_CITIES if "," in c}
_ALL_US_SENTINELS = {"all_us", "all us", "all us cities", "united states", "usa"}


def _split_location_segments(raw_location: str) -> list[str]:
    return [seg.strip() for seg in re.split(r"[;|/]+", raw_location) if seg.strip()]


def _has_non_us_marker(segment_lower: str) -> bool:
    for marker in NON_US_MARKERS:
        if re.search(rf"\b{re.escape(marker)}\b", segment_lower):
            return True
    abbr_match = re.search(r"(?:,\s*|-\s*|\()([a-z]{2})\s*(?:\)|$)", segment_lower.strip())
    if abbr_match and abbr_match.group(1) in _FOREIGN_COUNTRY_OR_PROVINCE_ABBRS:
        return True
    return False


def is_us_or_remote_location(segment: str, work_type_hint: str | None = None) -> bool:
    """Return True when a location segment resolves to the United States or US-compatible Remote."""
    seg = (segment or "").strip()
    if not seg:
        return True
    lower = seg.lower()
    if _has_non_us_marker(lower):
        return False

    if re.search(r"\b(?:us|u\.s\.|usa|united states)\b", lower):
        return True

    # Explicit ", ST" or "- ST" or standalone state code check (word-bounded)
    state_match = re.search(r"(?:,\s*|-\s*|\b)([a-z]{2})\b(?:\s*,\s*(?:us|usa|united states))?$", lower)
    if state_match and state_match.group(1) in US_STATE_ABBREVS:
        return True

    for state_name in US_STATE_NAMES:
        if re.search(rf"\b{re.escape(state_name)}\b", lower):
            return True

    for city_prefix in _ALL_CITY_PREFIXES:
        if re.search(rf"\b{re.escape(city_prefix)}\b", lower):
            return True

    if "remote" in lower or work_type_hint == "remote":
        return True

    # Reject ambiguous non-US strings
    return False


def _segment_matches_target(seg_lower: str, target_lower: str, work_type_hint: str | None = None) -> bool:
    if target_lower in _ALL_US_SENTINELS:
        return is_us_or_remote_location(seg_lower, work_type_hint)

    if "remote" in target_lower:
        if _has_non_us_marker(seg_lower):
            return False
        if "remote" in seg_lower or work_type_hint == "remote":
            return True
        return False

    city_part = target_lower.split(",")[0].strip()
    state_part = target_lower.split(",")[1].strip() if "," in target_lower else ""

    if city_part and re.search(rf"\b{re.escape(city_part)}\b", seg_lower):
        if state_part and len(state_part) == 2:
            # Guard same-named non-US cities (e.g., Portland, OR vs Portland; Cambridge, MA vs Cambridge, UK)
            if _has_non_us_marker(seg_lower):
                return False
        return True

    for key, aliases in CITY_ALIASES.items():
        if key == city_part or key in target_lower:
            for alias in aliases:
                if len(alias) > 2 and re.search(rf"\b{re.escape(alias)}\b", seg_lower):
                    if not _has_non_us_marker(seg_lower):
                        return True
    return False


def matches_target_location(
    location: str,
    target_locations: list[str],
    work_type_hint: str | None = None,
) -> bool:
    """Match a posting location string against target cities or US-only default guard."""
    raw_loc = (location or "").strip()
    if not raw_loc:
        return True

    target_lowers = [loc.strip().lower() for loc in target_locations if loc.strip()]
    # Focus exclusively on US & US-compatible Remote by default when no specific cities are selected
    wants_all_us = (not target_lowers) or any(t in _ALL_US_SENTINELS for t in target_lowers)
    wants_remote = any("remote" in t for t in target_lowers) or wants_all_us

    segments = _split_location_segments(raw_loc) or [raw_loc]
    for seg in segments:
        seg_lower = seg.lower()
        if wants_all_us and is_us_or_remote_location(seg, work_type_hint):
            return True
        if work_type_hint == "remote" and wants_remote and not _has_non_us_marker(seg_lower):
            return True
        for target_lower in target_lowers:
            if _segment_matches_target(seg_lower, target_lower, work_type_hint):
                return True

    return False
