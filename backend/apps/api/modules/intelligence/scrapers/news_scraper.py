"""
News Scraper — Company Intelligence Engine.

Searches public news sources for recent events about the company:
  - Funding rounds
  - Acquisitions
  - Expansion announcements
  - Product launches
  - Partnerships
  - Research programs
  - AI / Healthcare initiatives

Uses Tavily and Serper APIs for real-time news discovery.
Always returns gracefully — a missing news result never blocks enrichment.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# Event type classification keyword map
EVENT_KEYWORDS: dict[str, list[str]] = {
    "funding": ["funding", "raised", "series a", "series b", "series c", "investment", "investor", "venture", "seed round"],
    "acquisition": ["acqui", "merger", "acquired", "takeover", "buyout"],
    "expansion": ["expansion", "expand", "new office", "new market", "opened", "launch", "international"],
    "product_launch": ["launch", "new product", "introduced", "unveil", "released", "new platform", "new solution"],
    "partnership": ["partnership", "partner", "collaboration", "integrat", "alliance", "joint venture"],
    "research": ["research", "clinical trial", "study", "findings", "publication", "whitepaper"],
    "award": ["award", "recognized", "best", "ranked", "certified", "achievement"],
    "hiring": ["hiring", "growing team", "executive hire", "appointed", "chief", "vp of", "coo", "cto"],
    "ai_initiative": ["artificial intelligence", "ai initiative", "machine learning", "generative ai", "llm"],
    "healthcare_initiative": ["clinical", "patient care", "hospital system", "ehr", "health outcomes", "digital health"],
}


@dataclass
class NewsEvent:
    event_type: str
    headline: str
    summary: str
    source_name: str
    source_url: str
    published_date: Optional[datetime]
    relevance_score: float
    raw_text: str = ""


def _classify_event(text: str) -> str:
    """Return the primary event type detected in the text."""
    text_lower = text.lower()
    for event_type, keywords in EVENT_KEYWORDS.items():
        if any(k in text_lower for k in keywords):
            return event_type
    return "general_news"


def _score_relevance(text: str, company_name: str) -> float:
    """Score the relevance of a news article to this company (0-100)."""
    score = 50.0
    text_lower = text.lower()
    company_lower = company_name.lower()

    # Boost if company is mentioned prominently
    if company_lower in text_lower[:200]:
        score += 25
    elif company_lower in text_lower:
        score += 10

    # Boost for healthcare or AI content
    if any(k in text_lower for k in ["healthcare", "clinical", "hospital", "patient"]):
        score += 10
    if any(k in text_lower for k in ["ai", "artificial intelligence", "machine learning"]):
        score += 10

    return min(score, 100.0)


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Attempt to parse common date formats from news results."""
    if not date_str:
        return None
    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d",
        "%B %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str[:25], fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


class NewsScraper:
    """
    Searches public news for significant company events.
    Uses Tavily (primary) and Serper (fallback) for real-time results.
    """

    async def scrape(self, company_name: str, domain: Optional[str] = None) -> list[NewsEvent]:
        """
        Fetch recent public news events for the given company.
        Returns a list of structured NewsEvent objects.
        """
        events: list[NewsEvent] = []

        try:
            raw_results = await self._fetch_news(company_name, domain)
            seen_urls = set()

            for item in raw_results:
                url = item.get("url", "")
                if url in seen_urls:
                    continue
                seen_urls.add(url)

                text = f"{item.get('title', '')} {item.get('content', '')}"
                event_type = _classify_event(text)
                relevance = _score_relevance(text, company_name)

                event = NewsEvent(
                    event_type=event_type,
                    headline=item.get("title", "")[:500],
                    summary=item.get("content", "")[:2000],
                    source_name=item.get("source", item.get("domain", "Unknown")),
                    source_url=url,
                    published_date=_parse_date(item.get("published_date")),
                    relevance_score=relevance,
                    raw_text=text[:3000],
                )
                events.append(event)

        except Exception as exc:
            logger.warning("News scrape failed for '%s': %s", company_name, exc)

        # Sort by relevance score descending
        events.sort(key=lambda e: e.relevance_score, reverse=True)
        logger.info("News scrape complete for '%s' — %d events found", company_name, len(events))
        return events[:20]  # cap at 20 events per company

    async def _fetch_news(self, company_name: str, domain: Optional[str]) -> list[dict]:
        """Fetch raw news results from Tavily + Serper."""
        results: list[dict] = []

        queries = [
            f"{company_name} recent news funding partnership expansion 2024 2025",
            f"{company_name} AI healthcare digital transformation announcement",
        ]

        # Tavily (returns structured results with dates)
        try:
            from apps.api.core.tavily_provider import TavilyProvider
            tavily = TavilyProvider()
            if tavily.is_configured():
                for q in queries:
                    hits = tavily.search(q, max_results=8)
                    if isinstance(hits, list):
                        results.extend(hits)
                    elif isinstance(hits, str) and hits.strip():
                        results.append({"title": f"News about {company_name}", "content": hits, "url": ""})
        except Exception as exc:
            logger.debug("Tavily news search failed: %s", exc)

        # Serper fallback
        if len(results) < 5:
            try:
                from apps.api.modules.prospecting.engine.providers.serper_provider import SerperProvider
                provider = SerperProvider()
                if provider.is_enabled:
                    results.extend(await self._serper_news(provider, queries[0]))
            except Exception as exc:
                logger.debug("Serper news search failed: %s", exc)

        return results

    async def _serper_news(self, provider, query: str) -> list[dict]:
        """Fetch news via Serper News API endpoint."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://google.serper.dev/news",
                    headers={"X-API-KEY": provider._api_key, "Content-Type": "application/json"},
                    json={"q": query, "num": 10},
                )
                data = resp.json()
                return [
                    {
                        "title": r.get("title", ""),
                        "content": r.get("snippet", ""),
                        "url": r.get("link", ""),
                        "source": r.get("source", ""),
                        "published_date": r.get("date"),
                    }
                    for r in data.get("news", [])
                ]
        except Exception as exc:
            logger.debug("Serper news API error: %s", exc)
            return []
