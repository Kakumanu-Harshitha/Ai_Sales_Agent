"""
Website Scraper — Company Intelligence Engine.

Crawls important public pages of a company website and extracts clean,
structured text for AI analysis. Gracefully handles failures on any page
without stopping the overall enrichment process.

Priority page types:
  1. Homepage
  2. About
  3. Products / Services / Solutions
  4. Blog / News / Press
  5. Careers
  6. Leadership / Team
  7. Case Studies / Research
"""

import asyncio
import logging
import re
import httpx
from urllib.parse import urljoin, urlparse
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# Heuristic slugs used to identify important page types
PAGE_HEURISTICS = {
    "about": ["about", "about-us", "about_us", "who-we-are", "company", "our-story"],
    "products": ["products", "product", "platform", "platforms", "solutions", "solution", "services", "service"],
    "blog": ["blog", "insights", "resources"],
    "news": ["news", "press", "press-releases", "media", "announcements", "newsroom"],
    "careers": ["careers", "jobs", "join-us", "work-with-us", "hiring", "join"],
    "leadership": ["leadership", "team", "management", "executives", "our-team"],
    "case_studies": ["case-studies", "case-study", "success-stories", "customers", "references"],
    "contact": ["contact", "contact-us", "get-in-touch"],
}

# Request headers mimicking a regular browser visit
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Connection": "keep-alive",
}

FETCH_TIMEOUT = 15.0   # seconds per page
MAX_TEXT_LENGTH = 6000  # chars of text to keep per page


@dataclass
class ScrapedPage:
    page_type: str
    page_url: str
    page_title: str = ""
    raw_text: str = ""
    success: bool = True
    error: Optional[str] = None


class WebsiteScraper:
    """
    Discovers and scrapes company website pages.
    All errors are caught — the scraper is fully resilient.
    """

    def __init__(self, timeout: float = FETCH_TIMEOUT):
        self._timeout = timeout

    async def scrape(self, base_url: str) -> list[ScrapedPage]:
        """
        Entry point. Fetches the homepage first, then discovers subpages.
        Returns a list of ScrapedPage results (successful or failed).
        """
        if not base_url:
            return []

        base_url = self._normalize_url(base_url)
        results: list[ScrapedPage] = []

        async with httpx.AsyncClient(
            headers=BROWSER_HEADERS,
            timeout=self._timeout,
            follow_redirects=True,
            verify=False,  # some corp sites have self-signed certs
        ) as client:
            # Step 1: Scrape homepage
            homepage = await self._fetch_page(client, base_url, "homepage")
            results.append(homepage)

            if not homepage.success:
                logger.warning("Homepage fetch failed for %s — aborting scrape", base_url)
                return results

            # Step 2: Discover subpages from sitemap or links
            discovered = await self._discover_subpages(client, base_url, homepage.raw_text)

            # Step 3: Fetch each discovered subpage concurrently (capped at 6 parallel)
            sem = asyncio.Semaphore(6)

            async def fetch_with_sem(url, page_type):
                async with sem:
                    return await self._fetch_page(client, url, page_type)

            tasks = [fetch_with_sem(url, ptype) for ptype, url in discovered.items()]
            pages = await asyncio.gather(*tasks, return_exceptions=True)

            for p in pages:
                if isinstance(p, ScrapedPage):
                    results.append(p)
                elif isinstance(p, Exception):
                    logger.debug("Subpage fetch raised: %s", p)

        logger.info("Website scrape complete for %s — %d pages fetched", base_url, len(results))
        return results

    async def _discover_subpages(self, client: httpx.AsyncClient, base_url: str, homepage_html: str) -> dict[str, str]:
        """
        Tries multiple discovery strategies:
        1. Parse <a> tags from homepage HTML for known subpage patterns
        2. Attempt common URL suffixes as a fallback

        Returns a dict of {page_type: absolute_url}
        """
        found: dict[str, str] = {}
        base_domain = self._base_domain(base_url)

        # Strategy 1: Parse links from homepage
        href_pattern = re.compile(r'href=["\']([^"\'#?\s]+)["\']', re.IGNORECASE)
        hrefs = href_pattern.findall(homepage_html)

        for href in hrefs:
            full_url = urljoin(base_url, href)
            if base_domain not in full_url:
                continue  # Skip off-site links
            slug = urlparse(full_url).path.strip("/").lower()
            for page_type, patterns in PAGE_HEURISTICS.items():
                if page_type not in found:
                    for p in patterns:
                        if p in slug.split("/")[-1:] or slug == p:
                            found[page_type] = full_url
                            break

        # Strategy 2: Try guessed URLs for types not found
        for page_type, patterns in PAGE_HEURISTICS.items():
            if page_type not in found:
                for slug in patterns:
                    candidate = f"{base_url.rstrip('/')}/{slug}"
                    try:
                        r = await client.head(candidate, timeout=6.0)
                        if r.status_code < 400:
                            found[page_type] = candidate
                            break
                    except Exception:
                        pass

        logger.debug("Discovered subpages for %s: %s", base_url, list(found.keys()))
        return found

    async def _fetch_page(self, client: httpx.AsyncClient, url: str, page_type: str) -> ScrapedPage:
        """Fetch a single URL and extract clean text."""
        try:
            response = await client.get(url, timeout=self._timeout)
            response.raise_for_status()
            html = response.text
            title, text = self._extract_text(html)
            return ScrapedPage(
                page_type=page_type,
                page_url=url,
                page_title=title,
                raw_text=text[:MAX_TEXT_LENGTH],
                success=True,
            )
        except Exception as exc:
            logger.debug("Page fetch failed [%s] %s: %s", page_type, url, exc)
            return ScrapedPage(
                page_type=page_type,
                page_url=url,
                success=False,
                error=str(exc),
            )

    @staticmethod
    def _extract_text(html: str) -> tuple[str, str]:
        """Extract clean page title and body text from raw HTML."""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")

            # Remove noise elements
            for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript", "aside"]):
                tag.decompose()

            title = soup.title.get_text(strip=True) if soup.title else ""

            # Prefer main content areas
            main = soup.find("main") or soup.find(attrs={"id": "main"}) or soup.find(attrs={"role": "main"}) or soup.body
            text = main.get_text(separator=" ", strip=True) if main else soup.get_text(separator=" ", strip=True)

            # Collapse whitespace
            text = re.sub(r"\s{3,}", "  ", text).strip()
            return title, text
        except Exception as exc:
            logger.debug("Text extraction error: %s", exc)
            return "", ""

    @staticmethod
    def _normalize_url(url: str) -> str:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        # Remove trailing slashes
        return url.rstrip("/")

    @staticmethod
    def _base_domain(url: str) -> str:
        return urlparse(url).netloc
