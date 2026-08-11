"""
providers/tavily_provider.py - Tavily Search API provider.

Replaces Google CSE for AI-native company discovery. Tavily is purpose-built
for LLM agents, returning clean, structured markdown instead of noisy HTML snippets.

Graceful degradation:
  - is_enabled returns False when TAVILY_API_KEY is absent.
  - 401/403 -> ProviderAuthError
  - 429 -> ProviderQuotaExhaustedError
  - Timeout -> ProviderTimeoutError

Company discovery (search_companies):
  Generates 2-3 focused search intents deterministically from the ICPFilter
  (industry, keywords, region) to maximize result quality via concurrent search.
  Results from all intents are deduplicated by domain before returning.

Contact discovery (search_contacts):
  Builds a targeted query from the inferred organization type and fetches
  leadership/team page content using Tavily advanced search. Delegates to
  ContactExtractor (Groq) for full signal extraction including literal emails,
  phones, org type, and leadership page indicators.
  source_reliability is set to 75 (adjustable default).
"""

from __future__ import annotations

import asyncio
import logging
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

PROVIDER = ProviderName.TAVILY

_DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/\s]+)")
_SIZE_RE = re.compile(r"(\d[\d,]+)\s*(?:employees|staff|people|team members)", re.I)
_TAVILY_CONTACT_SOURCE_RELIABILITY = 75

_EXCLUDE_DOMAINS = [
    "wikipedia.org", "glassdoor.com", "indeed.com", "yelp.com",
    "zoominfo.com", "linkedin.com", "healthline.com", "webmd.com",
    "medscape.com", "beckershospitalreview.com", "fiercehealthcare.com",
    "modernhealthcare.com", "healthcareitnews.com", "hitconsultant.net",
    "healthaffairs.org", "statnews.com", "medium.com", "forbes.com",
    "businessinsider.com", "techcrunch.com", "bloomberg.com", "reuters.com",
    "npidb.org", "npino.com", "npiregistry.cms.hhs.gov",
    "bbb.org", "yellowpages.com", "manta.com", "crunchbase.com",
    "dnb.com", "bizbuysell.com", "mapquest.com", "tripadvisor.com",
]

_ORG_TYPE_KEYWORDS: list[tuple[str, list[str]]] = [
    ("hospital", ["hospital", "medical center", "health system", "health centre"]),
    ("clinic", ["clinic", "outpatient", "urgent care", "ambulatory"]),
    ("imaging center", ["imaging", "radiology", "mri", "ct scan", "x-ray"]),
    ("laboratory", ["laboratory", "lab ", "diagnostics", "pathology"]),
    ("home health", ["home health", "home care", "home healthcare", "homecare"]),
    ("rehab", ["rehabilitation", "rehab ", "physical therapy", "occupational therapy"]),
    ("practice", ["practice", "physician", "medical group", "medical office"]),
    ("dental", ["dental", "dentist", "orthodontic"]),
    ("mental health", ["mental health", "behavioral health", "psychiatry", "counseling"]),
]

_ORG_CONTACT_SEARCH_TERMS: dict[str, str] = {
    "hospital": "administration OR leadership OR chief OR director OR executive",
    "clinic": "physician OR director OR administrator OR leadership",
    "imaging center": "director OR administrator OR leadership",
    "laboratory": "director OR administrator OR leadership",
    "home health": "administrator OR director OR leadership",
    "rehab": "director OR administrator OR leadership",
    "practice": "physician OR director OR administrator",
    "dental": "dentist OR director OR administrator",
    "mental health": "director OR administrator OR leadership",
}
_DEFAULT_CONTACT_SEARCH_TERMS = "leadership OR administration OR team OR management OR director"


def _infer_org_type(text: str) -> str | None:
    """Infer organization type from title/content text."""
    text_lower = text.lower()
    for org_type, keywords in _ORG_TYPE_KEYWORDS:
        if any(kw in text_lower for kw in keywords):
            return org_type
    return None


class TavilyProvider(LeadDiscoveryProvider):
    """Tavily Search API adapter for AI-native healthcare company discovery."""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return self._settings.tavily_enabled

    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        if not self.is_enabled:
            return []

        queries = self._build_discovery_queries(icp)
        logger.info("Tavily: running %d discovery intents", len(queries))

        tasks = [self._search(q, max_results=8) for q in queries]
        results_per_query = await asyncio.gather(*tasks, return_exceptions=True)

        seen_domains: set[str] = set()
        seen_names: set[str] = set()
        results: list[CandidateCompany] = []

        for query_results in results_per_query:
            if isinstance(query_results, Exception):
                logger.warning("Tavily discovery intent failed: %s", query_results)
                continue
            for item in query_results:
                company = self._parse_search_item(item, icp)
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
                results.append(company)

        logger.info("Tavily: discovered %d unique candidate companies", len(results))
        return results

    async def search_contacts(
        self, company: CandidateCompany, target_roles: list[str]
    ) -> list[CandidateContact]:
        """Contact discovery via Tavily advanced search + Groq full signal extraction."""
        if not self.is_enabled:
            return []
        if not self._settings.groq_enabled:
            logger.debug(
                "Tavily contact extraction skipped for '%s': Groq not configured",
                company.name,
            )
            return []

        org_type = _infer_org_type(
            f"{company.name} {company.description or ''} {company.industry or ''}"
        )
        contact_terms = _ORG_CONTACT_SEARCH_TERMS.get(org_type or "", _DEFAULT_CONTACT_SEARCH_TERMS)

        domain_hint = f"site:{company.domain}" if company.domain else ""
        query = f"\"{company.name}\" {domain_hint} ({contact_terms})".strip()

        try:
            items = await self._search_with_content(query, max_results=5)
        except Exception as exc:
            logger.warning("Tavily contact search failed for '%s': %s", company.name, exc)
            return []

        if not items:
            return []

        page_text_parts = []
        source_url = None
        for item in items:
            content = item.get("raw_content") or item.get("content") or ""
            if content:
                page_text_parts.append(content)
            if source_url is None:
                source_url = item.get("url")

        combined_text = "\n\n".join(page_text_parts)
        if not combined_text.strip():
            return []

        from apps.api.modules.prospecting.engine.ai.contact_extractor import ContactExtractor  # noqa: PLC0415
        from apps.api.modules.prospecting.engine.ai.llm_client import LLMClient  # noqa: PLC0415

        llm_client = LLMClient()
        extractor = ContactExtractor(llm_client)

        raw_contacts, page_meta = await extractor.extract(
            page_text=combined_text,
            company_name=company.name,
            source_url=source_url,
        )

        extracted_org_type = page_meta.get("organization_type") or org_type
        is_leadership_page = page_meta.get("is_leadership_page", False)

        contacts: list[CandidateContact] = []
        for item in raw_contacts:
            name: str = item.get("name", "")
            title: str | None = item.get("title")
            parts = name.split(" ", 1)
            contacts.append(
                CandidateContact(
                    company_internal_id=company.internal_id,
                    first_name=parts[0] if parts else None,
                    last_name=parts[1] if len(parts) > 1 else None,
                    full_name=name,
                    title=title,
                    source_provider=PROVIDER,
                    source_reliability=_TAVILY_CONTACT_SOURCE_RELIABILITY,
                    raw_payload=item,
                    extracted_email=item.get("email"),
                    extracted_phone=item.get("phone"),
                    department=item.get("department"),
                    location=item.get("location"),
                    organization_type=extracted_org_type,
                    leadership_indicator=is_leadership_page,
                    extraction_confidence=float(item.get("confidence", 0.5)),
                    source_url=source_url,
                )
            )

        logger.info(
            "Tavily contact extraction: %d contact(s) for '%s' (org=%s, leadership=%s)",
            len(contacts), company.name, extracted_org_type, is_leadership_page,
        )
        return contacts

    def _build_discovery_queries(self, icp: ICPFilter) -> list[str]:
        """
        Generate 3 randomized, ICP-aware discovery search queries.

        Uses all available ICP fields: industries, keywords, regions,
        target_roles, technologies, and company_size hints.
        Randomizes template and term selection each call so identical
        ICP searches surface different results on repeat runs.
        """
        import random  # noqa: PLC0415

        industry = icp.industries[0] if icp.industries else "healthcare"
        keywords = list(icp.keywords)
        regions = [
            r for r in icp.regions
            if r.lower().strip() not in {"us", "usa", "united states", "canada"}
        ] or ["United States"]
        roles = list(icp.target_roles)
        technologies = list(icp.technologies)

        # Build size hint string
        size_hint = ""
        if icp.company_size_min and icp.company_size_max:
            size_hint = f"{icp.company_size_min}-{icp.company_size_max} employees"
        elif icp.company_size_max:
            size_hint = f"under {icp.company_size_max} employees"

        # Infer org types from ICP industries/keywords
        _ORG_POOL = [
            "hospital", "clinic", "medical center", "urgent care center",
            "health system", "physician practice", "dental office",
            "mental health center", "rehabilitation center",
            "imaging center", "laboratory", "nursing home",
            "home health agency", "ambulatory surgery center",
        ]
        all_terms = [t.lower() for t in icp.industries + icp.keywords]
        relevant_org_types = [
            ot for ot in _ORG_POOL
            if any(w in ot for w in all_terms)
        ]
        if not relevant_org_types:
            relevant_org_types = _ORG_POOL[:4]

        # Shuffle pools so each run picks different combos
        random.shuffle(regions)
        random.shuffle(keywords)
        random.shuffle(relevant_org_types)
        random.shuffle(roles)

        # Query template pool
        _TEMPLATES = [
            "{industry} {org_type} in {region} official website",
            "{org_type} {region} administration contact team",
            "{industry} organization {region} {role} staff",
            "{keyword} {industry} {region} healthcare provider",
            "{region} {org_type} directory official site",
            "{industry} {region} {org_type} about leadership",
            "{keyword} {org_type} {region} management",
            "{industry} providers {region} contact {role}",
            "{tech} adoption {org_type} {region}",
            "{size_hint} {industry} {org_type} {region}",
        ]
        random.shuffle(_TEMPLATES)

        queries: list[str] = []
        region_cycle = regions * 3  # Allow cycling
        org_cycle = (relevant_org_types * 3)
        role_cycle = (roles * 3) if roles else ["administrator"] * 3
        kw_cycle = (keywords * 3) if keywords else [industry] * 3
        tech_cycle = (technologies * 3) if technologies else [""] * 3

        for i, template in enumerate(_TEMPLATES):
            if len(queries) >= 3:
                break
            try:
                q = template.format(
                    industry=industry,
                    org_type=org_cycle[i % len(org_cycle)],
                    region=region_cycle[i % len(region_cycle)],
                    role=role_cycle[i % len(role_cycle)],
                    keyword=kw_cycle[i % len(kw_cycle)],
                    tech=tech_cycle[i % len(tech_cycle)],
                    size_hint=size_hint,
                ).strip()
                # Skip queries with empty placeholders
                if not q or q in queries:
                    continue
                if "  " in q or q.endswith(" "):
                    q = " ".join(q.split())
                # Skip if a key slot is blank (e.g. no technologies)
                if not all(q.split()):
                    continue
                queries.append(q)
            except (KeyError, IndexError):
                continue

        logger.debug("Tavily discovery queries: %s", queries)
        return queries[:3]


    async def _search_with_content(self, query: str, max_results: int = 5) -> list[dict[str, Any]]:
        """Advanced search returning raw page content for contact extraction."""
        payload = {
            "api_key": self._settings.tavily_api_key,
            "query": query,
            "search_depth": "advanced",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": True,
            "max_results": min(max_results, 5),
        }
        
        cache_key = f"tavily_adv_{query}_{max_results}"
        cached = api_response_cache.get(cache_key)
        if cached:
            logger.debug(f"Tavily cache hit for query: {query}")
            return cached

        url = f"{self._settings.tavily_base_url}/search"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, str(exc)) from exc
        if response.status_code in (401, 403):
            raise ProviderAuthError(PROVIDER.value, "Invalid Tavily API key.")
        if response.status_code == 429:
            raise ProviderQuotaExhaustedError(PROVIDER.value, "Tavily rate limit exhausted.")
        if response.status_code != 200:
            raise ProviderResponseError(PROVIDER.value, f"HTTP {response.status_code}: {response.text[:200]}")
        
        results = response.json().get("results") or []
        api_response_cache.set(cache_key, results)
        return results

    async def _search(self, query: str, max_results: int = 8) -> list[dict[str, Any]]:
        """Basic search for company discovery."""
        payload = {
            "api_key": self._settings.tavily_api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "max_results": min(max_results, 20),
            "exclude_domains": _EXCLUDE_DOMAINS,
        }
        
        cache_key = f"tavily_basic_{query}_{max_results}"
        cached = api_response_cache.get(cache_key)
        if cached:
            logger.debug(f"Tavily cache hit for query: {query}")
            return cached

        url = f"{self._settings.tavily_base_url}/search"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, str(exc)) from exc
        if response.status_code in (401, 403):
            raise ProviderAuthError(PROVIDER.value, "Invalid Tavily API key.")
        if response.status_code == 429:
            raise ProviderQuotaExhaustedError(PROVIDER.value, "Tavily rate limit exhausted.")
        if response.status_code != 200:
            raise ProviderResponseError(PROVIDER.value, f"HTTP {response.status_code}: {response.text[:200]}")
        
        results = response.json().get("results") or []
        api_response_cache.set(cache_key, results)
        return results

    def _parse_search_item(self, item: dict[str, Any], icp: ICPFilter) -> CandidateCompany | None:
        """Extract a CandidateCompany from a single Tavily search result."""
        title = item.get("title", "")
        url = item.get("url", "")
        content = item.get("content", "")
        if not title or not url:
            return None
        _ARTICLE_PATH_RE = re.compile(r"/(?:blog|news|article|post|press|story|update|\d{4})/", re.I)
        if _ARTICLE_PATH_RE.search(url):
            return None
        if len(title.split()) > 7:
            return None
        domain_match = _DOMAIN_RE.match(url)
        domain = domain_match.group(1) if domain_match else None
        name = re.sub(r"\s*[|\u2014\u2013-].*$", "", title).strip()
        if not name or len(name) < 2:
            return None
        _GENERIC_WORDS = {"english", "home", "about", "contact", "welcome", "main", "index"}
        if name.lower() in _GENERIC_WORDS:
            return None
        size_match = _SIZE_RE.search(content)
        employee_count = None
        if size_match:
            try:
                employee_count = int(size_match.group(1).replace(",", ""))
            except ValueError:
                pass
        industry = icp.industries[0] if icp.industries else None
        region = self._extract_mentioned_region(f"{title} {content}", icp)
        return CandidateCompany(
            name=name, domain=domain, website=url, industry=industry,
            hq_city=region, description=content[:500] if content else None,
            source_provider=PROVIDER, employee_count=employee_count, raw_payload=item,
        )

    @staticmethod
    def _extract_mentioned_region(text: str, icp: ICPFilter) -> str | None:
        """Return the first ICP region literally mentioned in text, or None."""
        if not icp.regions or not text:
            return None
        text_lower = text.lower()
        for region in icp.regions:
            if region and region.lower() in text_lower:
                return region
        return None
