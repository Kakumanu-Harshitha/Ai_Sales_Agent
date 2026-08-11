"""
services/decision_maker.py - DecisionMakerDiscoveryService.

Responsibility: For each candidate company, discover relevant decision
makers (contacts) using all registered discovery providers, merge every
result into a ContactCandidatePool, and return the full ranked list for
the orchestrator to select from.

Discovery order (P1 two-lane design):
  1. Apollo people search (if enabled) - source_reliability default: 90
  2. Tavily + Groq extraction            - source_reliability default: 70
  3. NPI / Healthcare Directory fallback - source_reliability default: 30

Source reliability values are starting defaults - review and tune after
observing real pipeline output.  They are set on each CandidateContact by
the provider (or overridden here for providers that don't set one).

All candidates are returned to the orchestrator; ContactCandidatePool
ranking then selects the best one before enrichment.
"""

from __future__ import annotations

import logging

from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from apps.api.modules.prospecting.engine.providers.base import LeadDiscoveryProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    ICPFilter,
)

logger = logging.getLogger(__name__)

# Maximum contacts to collect per company across all providers
MAX_CONTACTS_PER_COMPANY = 15

# Source reliability defaults per provider name value (adjustable).
# Applied when a provider returns a contact without setting source_reliability,
# or when we want to override the contact's own default for audit purposes.
_PROVIDER_RELIABILITY_DEFAULTS: dict[str, int] = {
    "apollo": 90,
    "pdl": 75,
    "tavily": 70,
    "npi_registry": 30,
    "healthcare_directory": 30,
}


class DecisionMakerDiscoveryService:
    """
    Discovers relevant contacts (decision makers) within a given company
    using all registered providers, merging every result into a single pool.

    Returns the full list of discovered contacts so the orchestrator's
    ContactCandidatePool can rank and select the best one.
    """

    def __init__(self, providers: list[LeadDiscoveryProvider]) -> None:
        self._providers = providers

    async def discover(
        self,
        company: CandidateCompany,
        icp: ICPFilter,
    ) -> list[CandidateContact]:
        """
        Discover decision makers at the given company from all enabled providers.

        Args:
            company: The company to search within.
            icp: ICP filter (used to extract target roles).

        Returns:
            Combined list of CandidateContact objects from all providers.
            May be empty if all providers fail or are disabled.
        """
        target_roles = icp.target_roles or _default_healthcare_roles()
        all_contacts: list[CandidateContact] = []
        import random
        providers_to_try = list(self._providers)
        random.shuffle(providers_to_try)

        for provider in providers_to_try:
            if not provider.is_enabled:
                continue

            if len(all_contacts) >= MAX_CONTACTS_PER_COMPANY:
                break

            try:
                found = await provider.search_contacts(company, target_roles)
                if found:
                    # Apply source reliability default for providers that don't set it
                    provider_name = provider.name.value
                    default_reliability = _PROVIDER_RELIABILITY_DEFAULTS.get(provider_name, 50)

                    normalized: list[CandidateContact] = []
                    for contact in found:
                        # If the contact is still at the schema default (50), apply
                        # the provider-specific default instead.
                        if contact.source_reliability == 50:
                            contact = contact.model_copy(
                                update={"source_reliability": default_reliability}
                            )
                        normalized.append(contact)

                    added = normalized[: MAX_CONTACTS_PER_COMPANY - len(all_contacts)]
                    all_contacts.extend(added)

                    logger.debug(
                        "DecisionMaker: provider '%s' found %d contact(s) for '%s' "
                        "(reliability_default=%d)",
                        provider_name, len(found), company.name, default_reliability,
                    )

            except (ProviderAuthError, ProviderQuotaExhaustedError) as exc:
                logger.warning(
                    "Decision maker discovery skipped provider '%s' for '%s': %s",
                    provider.name.value, company.name, exc,
                )
                continue
            except (ProviderRateLimitError, ProviderTimeoutError) as exc:
                logger.warning(
                    "Decision maker discovery timed out on provider '%s' for '%s': %s",
                    provider.name.value, company.name, exc,
                )
                continue
            except Exception as exc:
                logger.error(
                    "Decision maker discovery unexpected error for '%s' on '%s': %s",
                    company.name, provider.name.value, exc, exc_info=True,
                )
                continue

        if not all_contacts:
            logger.debug(
                "No decision makers found for '%s' across all providers - "
                "lead will be stored with empty contact (enrichment_status=partial)",
                company.name,
            )

        return all_contacts[:MAX_CONTACTS_PER_COMPANY]


def _default_healthcare_roles() -> list[str]:
    """
    Default set of healthcare IT decision maker titles used when ICP
    doesn't specify target_roles.
    """
    return [
        "Chief Technology Officer",
        "CTO",
        "Chief Information Officer",
        "CIO",
        "Chief Medical Officer",
        "CMO",
        "VP of Information Technology",
        "VP of IT",
        "Director of IT",
        "Director of Digital Health",
        "Director of Technology",
        "VP of Digital Transformation",
        "Chief Digital Officer",
        "CDO",
        "Health IT Manager",
    ]
