"""
providers/tinyfish_provider.py — TinyFish AI web agent for healthcare discovery.

TinyFish (tinyfish.ai) provides:
  - Search API: structured JSON web search results, LLM-optimized (free tier)
  - Fetch API: renders URLs and returns clean Markdown (free tier)

This provider uses TinyFish similarly to how we use Tavily — for company
discovery and contact page fetching — but with a different underlying index
and query strategy, surfacing complementary results.

Randomization: builds 3-5 query variants per run using shuffled ICP term
combinations so identical ICP searches produce different results each time.

Auth: TINYFISH_API_KEY via X-API-Key header.
Graceful degradation: returns [] if key is absent.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

import httpx

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from apps.api.modules.prospecting.engine.providers.base import LeadDiscoveryProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    ICPFilter,
    ProviderName,
)
from apps.api.core.cache import api_response_cache

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.TINYFISH

_SEARCH_URL = "https://api.search.tinyfish.ai/search"
_FETCH_URL = "https://api.fetch.tinyfish.ai/fetch"

_DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/\s]+)")
_SIZE_RE = re.compile(r"(\d[\d,]+)\s*(?:employees|staff|people|team members)", re.I)

_EXCLUDE_DOMAINS = [
    "wikipedia.org", "glassdoor.com", "indeed.com", "yelp.com",
    "zoominfo.com", "linkedin.com", "healthline.com", "webmd.com",
    "medscape.com", "beckershospitalreview.com", "modernhealthcare.com",
    "healthcareitnews.com", "healthaffairs.org", "medium.com", "forbes.com",
    "businessinsider.com", "techcrunch.com", "bloomberg.com", "reuters.com",
    "npidb.org", "npino.com", "npiregistry.cms.hhs.gov",
]

# Query templates — placeholders: {industry}, {region}, {role}, {keyword}, {size_hint}
_QUERY_TEMPLATES = [
    "{industry} {org_type} in {region} official website",
    "{org_type} {region} contact administration",
    "{industry} providers {region} leadership team",
    "{keyword} {org_type} in {region} -linkedin",
    "{region} {org_type} {role} directory",
    "{industry} organizations {region} about us",
    "{keyword} healthcare facility {region} management",
    "{org_type} network {region} executive staff",
]

_HEALTHCARE_ORG_TYPES = [
    "hospital", "clinic", "medical center", "health system",
    "urgent care", "imaging center", "laboratory", "rehab center",
    "dental practice", "mental health center", "home health agency",
    "nursing home", "ambulatory surgery center", "physician group",
]


class TinyFishProvider(LeadDiscoveryProvider):
    """
    TinyFish AI web search adapter for healthcare company discovery.

    Generates randomized, ICP-aware queries to complement Tavily results.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return self._settings.tinyfish_enabled

    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        if not self.is_enabled:
            return []

        queries = self._build_discovery_queries(icp)
        logger.info("TinyFish: running %d discovery queries", len(queries))

        tasks = [self._search(q, max_results=8) for q in queries]
        results_per_query = await asyncio.gather(*tasks, return_exceptions=True)

        seen_domains: set[str] = set()
        seen_names: set[str] = set()
        companies: list[CandidateCompany] = []

        for query_results in results_per_query:
            if isinstance(query_results, Exception):
                logger.warning("TinyFish query failed: %s", query_results)
                continue
            for item in query_results:
                company = self._parse_result(item, icp)
                if not company:
                    continue
                dedup_key = company.domain or company.name.lower().strip()
                if dedup_key in seen_domains:
                    continue
                name_key = re.sub(r"\s+", "", company.name.lower())
                if name_key in seen_names:
                    continue
                seen_domains.add(dedup_key)
                seen_names.add(name_key)
                companies.append(company)

        logger.info("TinyFish: discovered %d unique candidate companies", len(companies))
        return companies

    async def search_contacts(
        self, company: CandidateCompany, target_roles: list[str]
    ) -> list[CandidateContact]:
        # TinyFish contact search not implemented — Tavily handles this
        return []

    async def fetch_page(self, url: str) -> str:
        """
        Fetch a URL via TinyFish Fetch API and return clean Markdown content.
        Used by CompanyResearchService as an alternative to raw httpx scraping.
        """
        if not self.is_enabled:
            return ""

        cache_key = f"tinyfish_fetch_{url}"
        cached = api_response_cache.get(cache_key)
        if cached:
            return cached

        try:
            headers = {"X-API-Key": self._settings.tinyfish_api_key}
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    _FETCH_URL,
                    json={"url": url, "format": "markdown"},
                    headers=headers,
                )
            if response.status_code in (401, 403):
                raise ProviderAuthError(PROVIDER.value, "Invalid TinyFish API key.")
            if response.status_code == 429:
                raise ProviderQuotaExhaustedError(PROVIDER.value, "TinyFish rate limit.")
            if response.status_code != 200:
                return ""
            content = response.json().get("content") or response.json().get("markdown") or ""
            api_response_cache.set(cache_key, content)
            return content
        except (ProviderAuthError, ProviderQuotaExhaustedError):
            raise
        except Exception as exc:
            logger.debug("TinyFish fetch failed for %s: %s", url, exc)
            return ""

    def _build_discovery_queries(self, icp: ICPFilter) -> list[str]:
        """
        Build 3 randomized, ICP-aware search queries.

        Combines ICP industries, keywords, regions, and target_roles into
        query permutations. Randomizes template and term selection each call.
        """
        industry = icp.industries[0] if icp.industries else "healthcare"
        keywords = list(icp.keywords)
        regions = list(icp.regions)
        roles = list(icp.target_roles)

        # Filter out generic country-level regions
        regions = [
            r for r in regions
            if r.lower().strip() not in {"us", "usa", "united states", "canada"}
        ] or ["United States"]

        # Resolve relevant org types from ICP
        relevant_org_types = []
        all_terms = [t.lower() for t in icp.industries + icp.keywords]
        for org_type in _HEALTHCARE_ORG_TYPES:
            if any(word in org_type for word in all_terms):
                relevant_org_types.append(org_type)
        if not relevant_org_types:
            relevant_org_types = random.sample(_HEALTHCARE_ORG_TYPES, min(3, len(_HEALTHCARE_ORG_TYPES)))

        # Shuffle all pools for variety
        random.shuffle(regions)
        random.shuffle(keywords)
        random.shuffle(relevant_org_types)

        templates = random.sample(_QUERY_TEMPLATES, min(5, len(_QUERY_TEMPLATES)))
        queries: list[str] = []

        for template in templates:
            try:
                q = template.format(
                    industry=industry,
                    org_type=relevant_org_types[0] if relevant_org_types else "clinic",
                    region=regions[0] if regions else "United States",
                    role=roles[0] if roles else "administrator",
                    keyword=keywords[0] if keywords else industry,
                    size_hint=(
                        f"{icp.company_size_min}-{icp.company_size_max} employees"
                        if icp.company_size_min and icp.company_size_max else ""
                    ),
                ).strip()
                if q and q not in queries:
                    queries.append(q)
                    # Rotate pools for next query
                    if len(regions) > 1:
                        regions = regions[1:] + [regions[0]]
                    if len(relevant_org_types) > 1:
                        relevant_org_types = relevant_org_types[1:] + [relevant_org_types[0]]
            except (KeyError, IndexError):
                continue

        return queries[:3]

    async def _search(self, query: str, max_results: int = 8) -> list[dict[str, Any]]:
        """Call TinyFish Search API."""
        cache_key = f"tinyfish_search_{query}_{max_results}"
        cached = api_response_cache.get(cache_key)
        if cached is not None:
            logger.debug("TinyFish cache hit: %s", query)
            return cached

        headers = {"X-API-Key": self._settings.tinyfish_api_key}
        payload = {
            "query": query,
            "max_results": min(max_results, 10),
            "exclude_domains": _EXCLUDE_DOMAINS,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(_SEARCH_URL, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, repr(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, repr(exc)) from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError(PROVIDER.value, "Invalid TinyFish API key.")
        if response.status_code == 429:
            raise ProviderQuotaExhaustedError(PROVIDER.value, "TinyFish rate limit exhausted.")
        if response.status_code == 404:
            logger.debug("TinyFish returned 404 (no results found or endpoint unavailable).")
            return []
        if response.status_code != 200:
            raise ProviderResponseError(
                PROVIDER.value, f"HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()
        results = (
            data.get("results") or data.get("items") or data
            if isinstance(data, list) else []
        )
        if isinstance(data, dict):
            results = data.get("results") or data.get("items") or []

        api_response_cache.set(cache_key, results)
        return results

    def _parse_result(
        self, item: dict[str, Any], icp: ICPFilter
    ) -> CandidateCompany | None:
        """Parse a TinyFish search result into a CandidateCompany."""
        title = item.get("title") or item.get("name") or ""
        url = item.get("url") or item.get("link") or ""
        content = item.get("content") or item.get("snippet") or item.get("description") or ""

        if not title or not url:
            return None

        # Filter out article/news URLs
        if re.search(r"/(?:blog|news|article|post|press|story|update|\d{4})/", url, re.I):
            return None

        # Filter out excluded domains
        for excl in _EXCLUDE_DOMAINS:
            if excl in url:
                return None

        # Skip very long titles (likely article headlines)
        if len(title.split()) > 8:
            return None

        domain_match = _DOMAIN_RE.match(url)
        domain = domain_match.group(1) if domain_match else None

        # Clean up title to extract company name
        name = re.sub(r"\s*[|\u2014\u2013-].*$", "", title).strip()
        if not name or len(name) < 2:
            return None

        _GENERIC = {"english", "home", "about", "contact", "welcome", "main", "index", "search"}
        if name.lower() in _GENERIC:
            return None

        size_match = _SIZE_RE.search(content)
        employee_count = None
        if size_match:
            try:
                employee_count = int(size_match.group(1).replace(",", ""))
            except ValueError:
                pass

        industry = icp.industries[0] if icp.industries else "Healthcare"
        region = _extract_region(f"{title} {content}", icp)

        return CandidateCompany(
            name=name,
            domain=domain,
            website=url,
            industry=industry,
            hq_city=region,
            description=content[:500] if content else None,
            source_provider=PROVIDER,
            employee_count=employee_count,
            raw_payload=item,
        )


def _extract_region(text: str, icp: ICPFilter) -> str | None:
    """Return the first ICP region mentioned in text, or None."""
    if not icp.regions or not text:
        return None
    text_lower = text.lower()
    for region in icp.regions:
        if region and region.lower() in text_lower:
            return region
    return None
