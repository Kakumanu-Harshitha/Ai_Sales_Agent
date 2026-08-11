"""
services/company_research.py â€” CompanyResearchService.

Responsibility: Fetch a company's public website content and use the LLM
to extract structured context (summary, tech focus, digital transformation
signals, decision makers mentioned).

AI is used here because:
  - The input is unstructured HTML/text from diverse company websites.
  - Extracting 'digital transformation signals' requires semantic understanding.
  - Regex/rule-based extraction would fail on most company pages.

The service:
  1. Fetches the company's website (or domain) using httpx.
  2. Extracts readable text from the HTML (BeautifulSoup).
  3. Passes the text to CompanyResearcher (LLM).

All failures are non-fatal â€” the service returns None and the orchestrator
continues without company context.
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from apps.api.modules.prospecting.engine.ai.company_researcher import CompanyResearcher
from apps.api.modules.prospecting.engine.ai.groq_client import GroqClient
from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.schemas.internal import CandidateCompany, CompanyContext

logger = logging.getLogger(__name__)

# Pages to try in order when fetching company content — leadership/team pages
# included to maximize contact signal, followed by about pages for context.
_PAGE_PATHS = [
    "/leadership", "/team", "/about-us", "/about",
    "/company", "/who-we-are", "/our-team", "/staff", "",
]

# HTTP timeout for website fetching (separate from provider timeout)
_FETCH_TIMEOUT = 10

# Minimum page text length to pass to LLM
_MIN_TEXT_LENGTH = 100


class CompanyResearchService:
    """
    Fetches and synthesizes company context from public web pages.

    Completely optional â€” the orchestrator proceeds without it if it fails.
    """

    def __init__(self, groq_client: GroqClient) -> None:
        self._researcher = CompanyResearcher(groq_client)
        self._groq_enabled = get_settings().groq_enabled

    async def research(self, company: CandidateCompany) -> CompanyContext | None:
        """
        Fetch company website content and extract structured context via LLM.

        Args:
            company: The company to research.

        Returns:
            CompanyContext or None if research fails at any step.
        """
        if not self._groq_enabled:
            logger.debug(
                "Groq not configured â€” skipping company research for '%s'",
                company.name,
            )
            return None

        page_text, source_url = await self._fetch_company_page(company)

        if not page_text or len(page_text) < _MIN_TEXT_LENGTH:
            logger.debug(
                "No usable page content for '%s' — skipping LLM research",
                company.name,
            )
            return None

        # Extract any publicly visible emails from the page before LLM processing
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        scraped_emails = list(set(re.findall(email_pattern, page_text)))

        # NOTE: No hard truncation here. LLMClient handles this automatically:
        # - Gemini gets up to 4M chars (1M token context window)
        # - Cerebras/Mistral get up to 512k chars (128k context)
        # - Groq gets auto-truncated to 32k chars to fit its 8k TPM budget

        try:
            context = await self._researcher.research(
                company_name=company.name,
                page_text=page_text,
                source_url=source_url,
            )
            if context:
                context = context.model_copy(update={"scraped_emails": scraped_emails})
                logger.debug(
                    "Company research complete for '%s' (url=%s). Extracted %d emails.",
                    company.name, source_url, len(scraped_emails)
                )
            return context

        except Exception as exc:
            logger.warning(
                "Company research LLM call failed for '%s': %s",
                company.name, exc,
            )
            return None

    async def _fetch_company_page(
        self, company: CandidateCompany
    ) -> tuple[str, str | None]:
        """
        Fetch readable text from the company's website.

        Tries multiple URL patterns (about page first, then homepage).
        Returns (page_text, source_url) or ("", None) on failure.
        """
        base_url = self._resolve_base_url(company)
        if not base_url:
            return "", None

        async with httpx.AsyncClient(
            timeout=_FETCH_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "SETV-ProspectingAgent/1.0 (company research bot)"},
        ) as client:
            for path in _PAGE_PATHS:
                url = f"{base_url}{path}"
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        text = _extract_text(response.text)
                        if len(text) >= _MIN_TEXT_LENGTH:
                            return text, url
                except httpx.TimeoutException:
                    logger.debug("Timeout fetching '%s'", url)
                except Exception as exc:
                    logger.debug("Failed to fetch '%s': %s", url, exc)

        return "", None

    @staticmethod
    def _resolve_base_url(company: CandidateCompany) -> str | None:
        """Construct a fetchable base URL from whatever the company has."""
        if company.website:
            # Ensure protocol prefix
            url = company.website
            if not url.startswith("http"):
                url = f"https://{url}"
            return url.rstrip("/")

        if company.domain:
            return f"https://{company.domain}"

        return None


def _extract_text(html: str) -> str:
    """
    Extract clean, readable text from HTML.
    Removes scripts, styles, nav, footer noise.
    """
    try:
        soup = BeautifulSoup(html, "lxml")

        # Remove noise elements
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        # Prefer meaningful sections
        for selector in ["main", "article", '[class*="about"]', '[id*="about"]', "body"]:
            target = soup.select_one(selector)
            if target:
                text = target.get_text(separator=" ", strip=True)
                if len(text) >= _MIN_TEXT_LENGTH:
                    # Collapse whitespace
                    return re.sub(r"\s+", " ", text).strip()

        # Fallback: whole page text
        return re.sub(r"\s+", " ", soup.get_text(separator=" ", strip=True)).strip()

    except Exception as exc:
        logger.debug("HTML text extraction failed: %s", exc)
        return ""

