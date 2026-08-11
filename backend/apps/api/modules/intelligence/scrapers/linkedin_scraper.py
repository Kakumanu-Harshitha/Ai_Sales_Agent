"""
LinkedIn Intelligence Scraper — Company Intelligence Engine.

LinkedIn blocks direct HTTP crawling aggressively. This module uses
our existing search API providers (Serper / Tavily) to fetch publicly
available LinkedIn activity for a company via public search.

Strategy:
  1. Search for "{company name} site:linkedin.com/company" via Serper
  2. Search for "{company name} LinkedIn announcement OR hiring OR partnership"
  3. Parse and structure results into LinkedinInsight records
  4. Gracefully skip if no data is found or APIs fail
"""

import logging
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


@dataclass
class LinkedinActivity:
    post_type: str = "unknown"       # announcement, hiring, award, partnership, event
    headline: str = ""
    summary: str = ""
    source_url: str = ""
    published_date: Optional[datetime] = None
    raw_text: str = ""
    is_hiring: bool = False
    is_expansion: bool = False
    is_ai_initiative: bool = False
    is_healthcare_initiative: bool = False
    is_partnership: bool = False
    is_award: bool = False


HIRING_KEYWORDS = ["hiring", "job opening", "we're growing", "join us", "open role", "career", "jobs at"]
EXPANSION_KEYWORDS = ["expansion", "expand", "new office", "new location", "new market", "international", "global", "launch"]
AI_KEYWORDS = ["artificial intelligence", "machine learning", "ai initiative", "ai platform", "generative ai", "llm", "deep learning"]
HEALTHCARE_KEYWORDS = ["clinical", "hospital", "patient", "ehr", "healthcare", "health system", "care delivery", "medical"]
PARTNERSHIP_KEYWORDS = ["partnership", "partner with", "collaboration", "collaborated", "integrat", "alliance"]
AWARD_KEYWORDS = ["award", "recognized", "achievement", "certified", "ranked", "best place", "forbes", "gartner"]


def _classify_activity(text: str) -> dict:
    """Return boolean flags for detected activity types."""
    text_lower = text.lower()
    return {
        "is_hiring": any(k in text_lower for k in HIRING_KEYWORDS),
        "is_expansion": any(k in text_lower for k in EXPANSION_KEYWORDS),
        "is_ai_initiative": any(k in text_lower for k in AI_KEYWORDS),
        "is_healthcare_initiative": any(k in text_lower for k in HEALTHCARE_KEYWORDS),
        "is_partnership": any(k in text_lower for k in PARTNERSHIP_KEYWORDS),
        "is_award": any(k in text_lower for k in AWARD_KEYWORDS),
    }


def _infer_post_type(flags: dict) -> str:
    """Return the most specific post type from classification flags."""
    if flags["is_award"]:
        return "award"
    if flags["is_partnership"]:
        return "partnership"
    if flags["is_hiring"]:
        return "hiring"
    if flags["is_expansion"]:
        return "expansion"
    if flags["is_ai_initiative"] or flags["is_healthcare_initiative"]:
        return "initiative"
    return "announcement"


class LinkedinScraper:
    """
    Fetches publicly visible LinkedIn intelligence via Serper / Tavily search APIs.
    Never fails the parent enrichment — always returns an empty list on any error.
    """

    async def scrape(self, company_name: str, linkedin_url: Optional[str] = None) -> list[LinkedinActivity]:
        """
        Fetch LinkedIn activity for a company.
        Returns a list of structured LinkedinActivity objects.
        """
        results: list[LinkedinActivity] = []

        try:
            raw_results = await self._search_linkedin(company_name, linkedin_url)
            for item in raw_results:
                text = f"{item.get('title', '')} {item.get('content', '')}"
                flags = _classify_activity(text)
                post_type = _infer_post_type(flags)
                activity = LinkedinActivity(
                    post_type=post_type,
                    headline=item.get("title", "")[:255],
                    summary=item.get("content", "")[:1000],
                    source_url=item.get("url", ""),
                    raw_text=text[:2000],
                    **flags,
                )
                results.append(activity)
        except Exception as exc:
            logger.warning("LinkedIn scrape failed for '%s': %s", company_name, exc)

        logger.info("LinkedIn scrape complete for '%s' — %d activities found", company_name, len(results))
        return results

    async def _search_linkedin(self, company_name: str, linkedin_url: Optional[str]) -> list[dict]:
        """
        Uses Serper or Tavily to search for public LinkedIn company data.
        Returns raw search result dicts with 'title', 'content', 'url'.
        """
        queries = [
            f'"{company_name}" site:linkedin.com announcement OR hiring OR partnership OR award',
            f"{company_name} LinkedIn company news initiative healthcare AI",
        ]

        raw: list[dict] = []

        # Try Serper first
        try:
            from apps.api.modules.prospecting.engine.providers.serper_provider import SerperProvider
            provider = SerperProvider()
            if provider.is_enabled:
                for q in queries[:1]:
                    results = await self._serper_search(provider, q)
                    raw.extend(results)
                if raw:
                    return raw[:10]
        except Exception as exc:
            logger.debug("Serper LinkedIn search failed: %s", exc)

        # Try Tavily
        try:
            from apps.api.core.tavily_provider import TavilyProvider
            tavily = TavilyProvider()
            if tavily.is_configured():
                for q in queries:
                    hits = tavily.search(q, max_results=5)
                    if isinstance(hits, list):
                        raw.extend(hits)
                    elif isinstance(hits, str):
                        raw.append({"title": f"LinkedIn activity for {company_name}", "content": hits, "url": ""})
        except Exception as exc:
            logger.debug("Tavily LinkedIn search failed: %s", exc)

        return raw[:10]

    async def _serper_search(self, provider, query: str) -> list[dict]:
        """Adapter to call SerperProvider search and normalise result format."""
        import httpx
        results = []
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://google.serper.dev/search",
                    headers={"X-API-KEY": provider._api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": 10},
                )
                data = resp.json()
                for r in data.get("organic", []):
                    results.append({
                        "title": r.get("title", ""),
                        "content": r.get("snippet", ""),
                        "url": r.get("link", ""),
                    })
        except Exception as exc:
            logger.debug("Serper direct search error: %s", exc)
        return results
