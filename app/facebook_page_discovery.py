from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse
import xml.etree.ElementTree as ET

import requests


BING_RSS_SEARCH_URL = "https://www.bing.com/search"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0 Safari/537.36"
)
FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "mbasic.facebook.com",
}
FACEBOOK_BLOCKED_PATH_PREFIXES = (
    "/posts/",
    "/events/",
    "/reel/",
    "/share/",
    "/story.php",
    "/watch/",
    "/photo",
    "/photos/",
    "/permalink.php",
    "/groups/",
    "/marketplace/",
)
GENERIC_TOKENS = {
    "bar",
    "ballina",
    "pub",
    "restaurant",
    "the",
}


@dataclass
class FacebookPageCandidate:
    url: str
    title: str
    snippet: str
    score: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def discover_facebook_page_candidates(
    venue_name: str,
    town: str = "Ballina",
    county: str = "Mayo",
    website_url: str | None = None,
    max_candidates: int = 5,
    timeout: int = 20,
) -> list[FacebookPageCandidate]:
    seen_urls: set[str] = set()
    ranked: list[FacebookPageCandidate] = []

    if website_url:
        for raw_result in discover_from_website(website_url, timeout=timeout):
            append_candidate(ranked, seen_urls, raw_result, venue_name, town, county, source_bonus=0.22)

    queries = [
        f'"{venue_name}" "{town}" facebook',
        f'"{venue_name}" "{town}" "{county}" facebook',
        f'"{venue_name}" facebook',
    ]
    for query in queries:
        for raw_result in search_bing_rss(query=query, timeout=timeout):
            append_candidate(ranked, seen_urls, raw_result, venue_name, town, county, source_bonus=0.0)

    ranked.sort(key=lambda candidate: candidate.score, reverse=True)
    return ranked[:max_candidates]


def append_candidate(
    ranked: list[FacebookPageCandidate],
    seen_urls: set[str],
    raw_result: dict[str, str],
    venue_name: str,
    town: str,
    county: str,
    source_bonus: float = 0.0,
) -> None:
    canonical_url = canonicalize_facebook_page_url(raw_result["url"])
    if not canonical_url or canonical_url in seen_urls:
        return
    seen_urls.add(canonical_url)
    score, reasons = score_candidate(
        venue_name=venue_name,
        town=town,
        county=county,
        title=raw_result["title"],
        snippet=raw_result["snippet"],
        url=canonical_url,
    )
    if source_bonus:
        score = round(min(1.0, score + source_bonus), 3)
        reasons.append("found on official website")
    ranked.append(
        FacebookPageCandidate(
            url=canonical_url,
            title=raw_result["title"],
            snippet=raw_result["snippet"],
            score=score,
            reasons=reasons,
        )
    )


def discover_from_website(website_url: str, timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(
        website_url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return extract_facebook_candidates_from_website(response.text, website_url)


def extract_facebook_candidates_from_website(html_text: str, website_url: str) -> list[dict[str, str]]:
    href_pattern = re.compile(r'href="(?P<href>[^"]+)"', re.I)
    title_match = re.search(r"<title>(?P<title>.*?)</title>", html_text, re.I | re.S)
    page_title = strip_tags(html.unescape(title_match.group("title"))) if title_match else website_url
    results: list[dict[str, str]] = []
    for match in href_pattern.finditer(html_text):
        href = html.unescape(match.group("href"))
        if "facebook.com" not in href.lower():
            continue
        results.append({"url": href, "title": page_title, "snippet": f"Linked from {website_url}"})
    return results


def search_bing_rss(query: str, timeout: int = 20) -> list[dict[str, str]]:
    response = requests.get(
        BING_RSS_SEARCH_URL,
        params={"q": query, "format": "rss"},
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    return parse_bing_rss_results(response.text)


def parse_bing_rss_results(xml_text: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    results: list[dict[str, str]] = []
    for item in root.findall("./channel/item"):
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        snippet = item.findtext("description") or ""
        if link:
            results.append({"url": link, "title": title, "snippet": snippet})
    return results


def canonicalize_facebook_page_url(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in FACEBOOK_HOSTS:
        return None

    path = parsed.path.rstrip("/")
    lower_path = path.lower()
    if not path:
        return None
    if any(lower_path.startswith(prefix) for prefix in FACEBOOK_BLOCKED_PATH_PREFIXES):
        return None

    if lower_path == "/profile.php":
        profile_id = parse_qs(parsed.query).get("id")
        if profile_id:
            return f"https://www.facebook.com/profile.php?id={profile_id[0]}"
        return None

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return None
    if len(segments) > 1:
        return None
    slug = segments[0]
    if slug.lower() in {"pages", "pg", "people"}:
        return None
    return f"https://www.facebook.com/{slug}/"


def score_candidate(
    venue_name: str,
    town: str,
    county: str,
    title: str,
    snippet: str,
    url: str,
) -> tuple[float, list[str]]:
    reasons: list[str] = []
    haystack = " ".join(part for part in (title, snippet, url) if part).lower()
    venue_tokens = [token for token in tokenize(venue_name) if token not in GENERIC_TOKENS]
    town_token = town.lower()
    county_token = county.lower()
    url_slug = normalize_name(urlparse(url).path.rsplit("/", 2)[-2] if url.endswith("/") else urlparse(url).path.rsplit("/", 1)[-1])

    exact_phrase = normalize_name(venue_name)
    normalized_haystack = normalize_name(haystack)
    token_matches = sum(1 for token in venue_tokens if token in haystack)
    token_ratio = (token_matches / len(venue_tokens)) if venue_tokens else 0.0
    similarity = SequenceMatcher(None, exact_phrase, normalized_haystack).ratio()
    url_token_matches = sum(1 for token in venue_tokens if token in url_slug)
    url_token_ratio = (url_token_matches / len(venue_tokens)) if venue_tokens else 0.0

    score = similarity * 0.35 + token_ratio * 0.3 + url_token_ratio * 0.25
    if exact_phrase and exact_phrase in normalized_haystack:
        score += 0.12
        reasons.append("exact venue name")
    if token_matches:
        reasons.append(f"{token_matches}/{len(venue_tokens)} venue tokens")
    if url_token_matches:
        score += 0.1
        reasons.append(f"{url_token_matches}/{len(venue_tokens)} URL slug tokens")
    if town_token in haystack:
        score += 0.12
        reasons.append("mentions Ballina")
    if county_token in haystack:
        score += 0.05
        reasons.append("mentions Mayo")
    if "/profile.php?id=" in url:
        score -= 0.03
    if re.search(r"/(?:posts|events|reel)/", url, re.I):
        score -= 0.25
    score = max(0.0, min(1.0, score))
    return round(score, 3), reasons


def normalize_name(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("&", " and ")
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def tokenize(text: str) -> list[str]:
    return [token for token in normalize_name(text).split() if token]


def strip_tags(value: str) -> str:
    clean = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", clean).strip()


def best_confident_candidate(
    candidates: Iterable[FacebookPageCandidate],
    min_score: float = 0.72,
    min_gap: float = 0.08,
) -> FacebookPageCandidate | None:
    ordered = list(candidates)
    if not ordered:
        return None
    best = ordered[0]
    if best.score < min_score:
        return None
    if len(ordered) == 1:
        return best
    if best.score - ordered[1].score < min_gap:
        return None
    return best
