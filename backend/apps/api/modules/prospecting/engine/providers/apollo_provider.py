"""
providers/apollo_provider.py â€” Apollo API provider (primary discovery + enrichment).

Apollo is the primary commercial prospecting source.
  - Company discovery: POST /mixed_companies/search
  - People/contact search: POST /people/search
  - Contact email enrichment: POST /people/match

Graceful degradation:
  - 401 â†’ ProviderAuthError (bad key)
  - 402 â†’ ProviderQuotaExhaustedError (free-tier exhausted)
  - 429 â†’ ProviderRateLimitError (backoff + retry handled by caller via tenacity)
  - Timeout â†’ ProviderTimeoutError
  - is_enabled returns False when APOLLO_API_KEY is absent
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitError,
    ProviderResponseError,
    ProviderTimeoutError,
)
from apps.api.modules.prospecting.engine.providers.base import EnrichmentProvider, LeadDiscoveryProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    EnrichedContact,
    EnrichmentStatus,
    ICPFilter,
    ProviderName,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.APOLLO


class ApolloProvider(LeadDiscoveryProvider, EnrichmentProvider):
    """
    Apollo.io API adapter.

    Implements both LeadDiscoveryProvider (company + people search)
    and EnrichmentProvider (email lookup via people/match).
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base_url = self._settings.apollo_base_url
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return self._settings.apollo_enabled

    # â”€â”€â”€ Company Discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        if not self.is_enabled or not self._settings.apollo_discovery_enabled:
            return []

        payload = self._build_company_search_payload(icp)

        data = await self._post("/mixed_companies/search", payload)
        organizations = data.get("organizations") or data.get("accounts") or []

        results = [self._parse_organization(org) for org in organizations]
        logger.info("Apollo: discovered %d companies", len(results))
        return results

    def _build_company_search_payload(self, icp: ICPFilter) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "per_page": min(icp.max_results, 25),  # Apollo free tier limit
            "page": 1,
        }

        if icp.industries:
            payload["q_organization_industry_tag_ids"] = icp.industries

        if icp.keywords:
            payload["q_organization_keyword_tags"] = icp.keywords

        # Size range: Apollo uses strings like "1,10" or "11,50"
        if icp.company_size_min is not None or icp.company_size_max is not None:
            min_val = icp.company_size_min or 1
            max_val = icp.company_size_max or 100000
            payload["num_employees_ranges"] = [f"{min_val},{max_val}"]

        if icp.regions:
            payload["organization_locations"] = icp.regions

        return payload

    def _parse_organization(self, org: dict[str, Any]) -> CandidateCompany:
        return CandidateCompany(
            name=org.get("name", "Unknown"),
            domain=org.get("primary_domain") or org.get("website_url", "").replace("https://", "").replace("http://", "").split("/")[0] or None,
            website=org.get("website_url"),
            industry=org.get("industry"),
            employee_count=org.get("estimated_num_employees"),
            employee_range=self._employee_range(org),
            hq_city=org.get("city"),
            hq_state=org.get("state"),
            hq_country=org.get("country"),
            description=org.get("short_description"),
            linkedin_url=org.get("linkedin_url"),
            source_provider=PROVIDER,
            raw_payload=org,
        )

    @staticmethod
    def _employee_range(org: dict[str, Any]) -> str | None:
        low = org.get("employee_count_range_min")
        high = org.get("employee_count_range_max")
        if low and high:
            return f"{low}-{high}"
        return None

    # â”€â”€â”€ People / Contact Discovery â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def search_contacts(
        self, company: CandidateCompany, target_roles: list[str]
    ) -> list[CandidateContact]:
        if not self.is_enabled or not self._settings.apollo_enrichment_enabled:
            return []

        payload: dict[str, Any] = {
            "per_page": 10,
            "page": 1,
        }

        if company.domain:
            payload["q_organization_domains"] = [company.domain]
        else:
            payload["q_organization_name"] = company.name

        if target_roles:
            payload["person_titles"] = target_roles

        data = await self._post("/people/search", payload)
        people = data.get("people") or []

        results = [
            self._parse_person(person, company.internal_id) for person in people
        ]
        logger.debug(
            "Apollo: found %d contacts for company '%s'",
            len(results), company.name,
        )
        return results

    def _parse_person(
        self, person: dict[str, Any], company_internal_id: str
    ) -> CandidateContact:
        return CandidateContact(
            company_internal_id=company_internal_id,
            first_name=person.get("first_name"),
            last_name=person.get("last_name"),
            full_name=person.get("name"),
            title=person.get("title"),
            email=person.get("email"),
            phone=person.get("phone_number"),
            linkedin_url=person.get("linkedin_url"),
            source_provider=PROVIDER,
            raw_payload=person,
        )

    # â”€â”€â”€ Email Enrichment â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def enrich_contact(
        self,
        contact: CandidateContact,
        company_domain: str | None,
    ) -> EnrichedContact:
        """
        Attempt to resolve email via Apollo people/match endpoint.
        Returns EnrichedContact even if no data found (enrichment_status=PARTIAL).
        """
        if not self.is_enabled:
            return _no_enrichment(contact, [])

        payload: dict[str, Any] = {}
        if contact.first_name:
            payload["first_name"] = contact.first_name
        if contact.last_name:
            payload["last_name"] = contact.last_name
        if company_domain:
            payload["domain"] = company_domain
        if contact.linkedin_url:
            payload["linkedin_url"] = contact.linkedin_url

        try:
            data = await self._post("/people/match", payload)
            person = data.get("person") or {}
        except (ProviderQuotaExhaustedError, ProviderAuthError):
            raise
        except Exception:
            return _no_enrichment(contact, [PROVIDER])

        email = person.get("email") or contact.email
        phone = person.get("phone_number") or contact.phone
        linkedin = person.get("linkedin_url") or contact.linkedin_url

        has_email = bool(email)
        has_phone = bool(phone)

        return EnrichedContact(
            source_contact=contact,
            email=email,
            email_verification_status=(
                VerificationStatus.UNVERIFIED if has_email else VerificationStatus.UNVERIFIED
            ),
            phone=phone,
            phone_verification_status=VerificationStatus.UNVERIFIED,
            linkedin_url=linkedin,
            enrichment_status=(
                EnrichmentStatus.FULL if has_email else EnrichmentStatus.PARTIAL
            ),
            enrichment_providers_used=[PROVIDER],
        )

    # â”€â”€â”€ HTTP Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self._settings.apollo_api_key or "",
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, f"Network error: {exc}") from exc

        return self._handle_response(response)

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        status = response.status_code

        if status == 200 or status == 201:
            try:
                return response.json()
            except Exception as exc:
                raise ProviderResponseError(
                    PROVIDER.value, f"Invalid JSON response: {exc}"
                ) from exc

        if status == 401:
            raise ProviderAuthError(PROVIDER.value, "Invalid or missing API key.")

        if status == 402:
            raise ProviderQuotaExhaustedError(
                PROVIDER.value,
                "Apollo free-tier quota exhausted. Falling back to next provider.",
            )

        if status == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            raise ProviderRateLimitError(
                PROVIDER.value,
                f"Rate limited. Retry after: {retry_after}s.",
            )

        raise ProviderResponseError(
            PROVIDER.value,
            f"Unexpected HTTP {status}: {response.text[:200]}",
        )


# â”€â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _no_enrichment(
    contact: CandidateContact, providers_tried: list[ProviderName]
) -> EnrichedContact:
    """Return an EnrichedContact carrying over whatever the contact already had."""
    return EnrichedContact(
        source_contact=contact,
        email=contact.email,
        phone=contact.phone,
        linkedin_url=contact.linkedin_url,
        enrichment_status=EnrichmentStatus.PARTIAL,
        enrichment_providers_used=providers_tried,
    )

