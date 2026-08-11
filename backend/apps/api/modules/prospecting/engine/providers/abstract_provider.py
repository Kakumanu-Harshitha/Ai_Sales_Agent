"""
providers/abstract_provider.py — Abstract API company enrichment.

Abstract API's Company Enrichment endpoint gives us structured company data
(industry, employee count, website, LinkedIn, description) from a domain or
company name. This fills in gaps left by discovery providers.

Free tier:
  - 1,000 free requests per month (no credit card required)
  - Sign up at: https://www.abstractapi.com/api/company-enrichment-api

Use case in our pipeline:
  This provider is used in a NEW step inserted after company discovery:
  "Company Enrichment" — before qualification. For each discovered company
  that is missing key fields (employee_count, description, domain),
  we call Abstract API to fill those in so the ICP qualification
  score is more accurate.

Implementation note:
  Abstract API doesn't implement LeadDiscoveryProvider or EnrichmentProvider
  because it enriches *companies*, not contacts. It is invoked directly by
  the orchestrator's _company_pipeline() as an optional pre-qualification step.
  This is a standalone service class, not a provider ABC subclass.

API Docs: https://docs.abstractapi.com/company-enrichment
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from apps.api.modules.prospecting.engine.schemas.internal import CandidateCompany, ProviderName

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.ABSTRACT_API


class AbstractCompanyEnricher:
    """
    Enriches CandidateCompany records with data from Abstract API.

    Not a LeadDiscoveryProvider — called by the orchestrator as
    an optional pre-qualification step to fill company data gaps.
    Always returns a CandidateCompany (may be identical to input if
    the API returns nothing useful or is disabled).
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def is_enabled(self) -> bool:
        return self._settings.abstract_enabled

    async def enrich(self, company: CandidateCompany) -> CandidateCompany:
        """
        Attempt to enrich company data via Abstract API.

        Args:
            company: The company discovered by a discovery provider.

        Returns:
            A CandidateCompany with any missing fields filled in.
            Returns the original company unchanged if enrichment fails.
        """
        if not self.is_enabled:
            return company

        # Only enrich if we're missing key qualification fields
        if company.employee_count and company.industry and company.description:
            logger.debug(
                "Abstract: company '%s' already fully enriched — skipping", company.name
            )
            return company

        domain = company.domain or _extract_domain(company.website)
        if not domain:
            logger.debug(
                "Abstract: no domain for '%s' — cannot enrich", company.name
            )
            return company

        try:
            data = await self._fetch(domain)
            if data:
                return _apply_enrichment(company, data)
        except (ProviderAuthError, ProviderQuotaExhaustedError):
            raise
        except ProviderTimeoutError:
            logger.warning("Abstract: timeout enriching '%s'", company.name)
        except Exception as exc:
            logger.debug("Abstract: enrichment failed for '%s': %s", company.name, exc)

        return company

    async def _fetch(self, domain: str) -> dict[str, Any] | None:
        """Call Abstract API and return raw data dict."""
        params = {
            "api_key": self._settings.abstract_api_key,
            "domain": domain,
        }

        url = self._settings.abstract_base_url

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, str(exc)) from exc

        if response.status_code == 200:
            try:
                return response.json()
            except Exception as exc:
                raise ProviderResponseError(PROVIDER.value, f"Invalid JSON: {exc}") from exc

        if response.status_code == 401:
            raise ProviderAuthError(PROVIDER.value, "Invalid Abstract API key.")

        if response.status_code in (402, 429):
            raise ProviderQuotaExhaustedError(
                PROVIDER.value,
                "Abstract API quota exhausted for this month.",
            )

        if response.status_code == 404:
            # Company not found in Abstract's database — not an error
            return None

        raise ProviderResponseError(
            PROVIDER.value,
            f"HTTP {response.status_code}: {response.text[:200]}",
        )


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _apply_enrichment(
    company: CandidateCompany, data: dict[str, Any]
) -> CandidateCompany:
    """Merge Abstract API data into the existing CandidateCompany (fill gaps only)."""

    # Abstract API response field mapping
    employee_count = data.get("employee_count") or data.get("employees_range")
    if isinstance(employee_count, str) and "-" in employee_count:
        # Try to convert a range like "51-200" to an int midpoint
        try:
            lo, hi = employee_count.split("-")
            employee_count_int = (int(lo.strip()) + int(hi.strip())) // 2
        except Exception:
            employee_count_int = None
        employee_range = employee_count
        employee_count = employee_count_int
    elif isinstance(employee_count, int):
        employee_range = None
        employee_count = employee_count
    else:
        employee_count = None
        employee_range = None

    locality = data.get("locality") or {}
    city = data.get("city") or (locality.get("city") if isinstance(locality, dict) else None)
    state = data.get("region") or data.get("state") or (locality.get("region") if isinstance(locality, dict) else None)
    country = data.get("country") or (locality.get("country") if isinstance(locality, dict) else None)

    linkedin = data.get("linkedin_url") or data.get("linkedin")
    if linkedin and not linkedin.startswith("http"):
        linkedin = f"https://linkedin.com/company/{linkedin}"

    updates: dict[str, Any] = {}

    if not company.industry and data.get("industry"):
        updates["industry"] = str(data["industry"])
    if not company.employee_count and employee_count:
        updates["employee_count"] = employee_count
    if not company.employee_range and employee_range:
        updates["employee_range"] = employee_range
    if not company.description and data.get("long_description"):
        updates["description"] = str(data["long_description"])[:500]
    elif not company.description and data.get("description"):
        updates["description"] = str(data["description"])[:500]
    if not company.hq_city and city:
        updates["hq_city"] = str(city)
    if not company.hq_state and state:
        updates["hq_state"] = str(state)
    if not company.hq_country and country:
        updates["hq_country"] = str(country)
    if not company.linkedin_url and linkedin:
        updates["linkedin_url"] = linkedin
    if not company.website and data.get("website_url"):
        updates["website"] = str(data["website_url"])

    if updates:
        logger.debug(
            "Abstract: enriched '%s' with fields: %s",
            company.name, list(updates.keys()),
        )
        return company.model_copy(update=updates)

    return company


def _extract_domain(website: str | None) -> str | None:
    """Extract a bare domain from a URL."""
    if not website:
        return None
    import re
    match = re.search(r"(?:https?://)?(?:www\.)?([^/\s]+)", website)
    return match.group(1).lower() if match else None
