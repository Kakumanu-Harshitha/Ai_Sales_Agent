"""
providers/osint_provider.py — OSINT Email Harvesting enrichment provider.

Inspired by theHarvester open-source OSINT tool (from HuggingFace blog).

Role: Enrichment provider (EnrichmentProvider). Sits in the waterfall
AFTER Prospeo/Hunter, BEFORE SMTP pattern fallback.

What it does:
  Given a known contact (name + domain), searches the open web for email
  addresses that have been publicly published on external sites such as:
    - Conference and event speaker pages
    - Medical association member directories
    - Research publication author metadata
    - Hospital/clinic board pages that link externally
    - Job posting sites that reveal applicant contact info

Technique:
  Uses the existing Tavily API (no new cost or signup) to run a targeted
  search query: '"@domain.com" "FirstName LastName"' and extracts email
  addresses from the returned content via regex.

Why this is different from TavilyProvider.search_contacts():
  - search_contacts() discovers WHO works at a company (broad leadership search)
  - OSINTProvider finds the ACTUAL EMAIL ADDRESS of a person already identified
  - The queries are fundamentally different: one is about people, one is about emails

No new API key required — reuses TAVILY_API_KEY.
"""

from __future__ import annotations

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
from apps.api.modules.prospecting.engine.providers.base import EnrichmentProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateContact,
    EnrichedContact,
    EnrichmentStatus,
    ProviderName,
    VerificationStatus,
)
from apps.api.core.cache import api_response_cache

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.OSINT

# Regex to extract email addresses from text
_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}\b"
)

# Email patterns that are clearly not personal (generic inboxes to skip)
_GENERIC_EMAIL_PREFIXES = {
    "info", "contact", "admin", "support", "hello", "help", "sales",
    "marketing", "noreply", "no-reply", "webmaster", "postmaster",
    "office", "team", "mail", "inquiry", "enquiry", "hr", "jobs",
}


class OSINTProvider(EnrichmentProvider):
    """
    OSINT email harvesting enrichment provider.

    Searches the open web for publicly posted email addresses matching
    the contact's name and domain. Uses the existing Tavily API key.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        # Requires Tavily to be configured
        return self._settings.tavily_enabled

    async def enrich_contact(
        self,
        contact: CandidateContact,
        company_domain: str | None,
    ) -> EnrichedContact:
        """
        Search for a publicly published email for this contact.

        Attempts multiple query strategies and returns the first
        domain-matching personal email found.
        """
        if not self.is_enabled or not company_domain:
            return self._passthrough(contact)

        # Already have an email — just pass through
        if contact.email:
            return self._passthrough(contact)

        first = (contact.first_name or "").strip()
        last = (contact.last_name or "").strip()
        full = (contact.full_name or "").strip()

        if not (first or full):
            return self._passthrough(contact)

        name_query = f'"{first} {last}"' if first and last else f'"{full}"'
        domain_query = f'"@{company_domain}"'

        queries = [
            f'{domain_query} {name_query}',
            f'{name_query} {company_domain} email contact',
            f'{domain_query} {first or full.split()[0]} -site:{company_domain}',
        ]

        for query in queries:
            try:
                emails = await self._search_for_emails(query, company_domain)
                if emails:
                    found_email = emails[0]
                    logger.info(
                        "OSINTProvider: found email '%s' for '%s' via open web",
                        found_email,
                        contact.display_name,
                    )
                    return EnrichedContact(
                        source_contact=contact,
                        email=found_email,
                        email_verification_status=VerificationStatus.UNVERIFIED,
                        phone=contact.phone,
                        linkedin_url=contact.linkedin_url,
                        enrichment_status=EnrichmentStatus.PARTIAL,
                        enrichment_providers_used=[PROVIDER],
                    )
            except ProviderQuotaExhaustedError:
                logger.warning("OSINTProvider: Tavily quota exhausted — skipping")
                break
            except ProviderAuthError:
                logger.error("OSINTProvider: Tavily auth error")
                break
            except Exception as exc:
                logger.debug("OSINTProvider: query failed — %s", exc)
                continue

        return self._passthrough(contact)

    async def _search_for_emails(
        self, query: str, domain: str
    ) -> list[str]:
        """
        Run a Tavily search and extract domain-matching email addresses
        from the returned content snippets.
        """
        cache_key = f"osint_search_{query}"
        cached = api_response_cache.get(cache_key)
        if cached is not None:
            return cached

        payload = {
            "api_key": self._settings.tavily_api_key,
            "query": query,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False,
            "max_results": 5,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    "https://api.tavily.com/search",
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, str(exc)) from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError(PROVIDER.value, "Invalid Tavily API key.")
        if response.status_code == 429:
            raise ProviderQuotaExhaustedError(PROVIDER.value, "Tavily quota exhausted.")
        if response.status_code != 200:
            raise ProviderResponseError(
                PROVIDER.value, f"HTTP {response.status_code}"
            )

        results = response.json().get("results") or []

        # Concatenate all content snippets
        all_text = " ".join(
            (r.get("content") or r.get("snippet") or "") for r in results
        )

        # Extract emails from text, filter to target domain only
        found: list[str] = []
        seen: set[str] = set()
        for match in _EMAIL_RE.finditer(all_text):
            email = match.group(0).lower()
            if domain.lower() not in email:
                continue
            prefix = email.split("@")[0]
            if prefix in _GENERIC_EMAIL_PREFIXES:
                continue
            if email not in seen:
                seen.add(email)
                found.append(email)

        api_response_cache.set(cache_key, found)
        return found

    def _passthrough(self, contact: CandidateContact) -> EnrichedContact:
        """Return EnrichedContact preserving whatever the contact already has."""
        return EnrichedContact(
            source_contact=contact,
            email=contact.email,
            phone=contact.phone,
            linkedin_url=contact.linkedin_url,
            enrichment_status=EnrichmentStatus.PARTIAL,
            enrichment_providers_used=[],
        )
