"""
services/enrichment.py â€” ContactEnrichmentService.

Responsibility: Given a CandidateContact and company domain, resolve as
much contact information as possible (email, phone, social profiles)
using registered enrichment providers in fallback order.

Fallback chain:
  1. Hunter.io (primary) â€” best email resolution
  2. Apollo (fallback) â€” backup if Hunter is absent or quota exhausted

The service merges results from successful providers. It NEVER raises on
'not found' â€” it always returns an EnrichedContact, possibly with
enrichment_status=PARTIAL if no email was resolved.
"""

from __future__ import annotations

import logging

from apps.api.modules.prospecting.engine.core.exceptions import ProviderAuthError, ProviderQuotaExhaustedError
from apps.api.modules.prospecting.engine.providers.base import EnrichmentProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    EnrichedContact,
    EnrichmentStatus,
    ProviderName,
)

logger = logging.getLogger(__name__)


class ContactEnrichmentService:
    """
    Enriches contact data via a prioritized chain of enrichment providers.

    Providers are tried in order. If Hunter.io is not configured or fails,
    the service automatically falls back to Apollo. If all providers fail
    or have no data, an EnrichedContact with status=PARTIAL is returned.
    """

    def __init__(self, enrichment_providers: list[EnrichmentProvider]) -> None:
        """
        Args:
            enrichment_providers: Ordered list of enrichment providers.
                                   Hunter.io should be first; Apollo second.
        """
        self._providers = enrichment_providers

    async def enrich(
        self,
        contact: CandidateContact,
        company: CandidateCompany,
    ) -> EnrichedContact:
        """
        Enrich a contact with email, phone, and social profiles.

        Args:
            contact: The contact to enrich.
            company: The associated company (used for domain resolution).

        Returns:
            EnrichedContact â€” always returns, never raises.
        """
        company_domain = company.domain
        providers_tried: list[ProviderName] = []
        last_result: EnrichedContact | None = None

        for provider in self._providers:
            if not provider.is_enabled:
                logger.debug(
                    "Enrichment provider '%s' disabled â€” skipping",
                    provider.name.value,
                )
                continue

            providers_tried.append(provider.name)

            try:
                result = await provider.enrich_contact(contact, company_domain)
                last_result = result

                # If we got a verified email, we're done
                if result.email and result.enrichment_status == EnrichmentStatus.FULL:
                    logger.debug(
                        "Contact '%s' fully enriched by provider '%s'",
                        contact.display_name, provider.name.value,
                    )
                    return result

                # Got partial data â€” continue to next provider to fill gaps
                if result.email:
                    logger.debug(
                        "Contact '%s': partial enrichment from '%s' â€” trying next provider",
                        contact.display_name, provider.name.value,
                    )
                    # Carry forward what we have and merge with next provider
                    contact = _apply_partial_enrichment(contact, result)

            except ProviderQuotaExhaustedError as exc:
                logger.warning(
                    "Enrichment provider '%s' quota exhausted for '%s': %s",
                    provider.name.value, contact.display_name, exc,
                )
                continue

            except ProviderAuthError as exc:
                logger.error(
                    "Enrichment provider '%s' auth error for '%s': %s",
                    provider.name.value, contact.display_name, exc,
                )
                continue

            except Exception as exc:
                logger.warning(
                    "Enrichment provider '%s' failed for '%s': %s",
                    provider.name.value, contact.display_name, exc,
                )
                continue

        # Return the last successful partial result, or a plain pass-through
        if last_result is not None:
            logger.debug(
                "Contact '%s' enrichment finished with status=%s (providers tried: %s)",
                contact.display_name,
                last_result.enrichment_status.value,
                [p.value for p in providers_tried],
            )
            return last_result

        # No provider succeeded at all â€” return pass-through with what we have
        logger.warning(
            "No enrichment provider returned data for '%s'",
            contact.display_name,
        )
        return EnrichedContact(
            source_contact=contact,
            email=contact.email,
            phone=contact.phone,
            linkedin_url=contact.linkedin_url,
            enrichment_status=EnrichmentStatus.PARTIAL,
            enrichment_providers_used=providers_tried,
        )


def _apply_partial_enrichment(
    original: CandidateContact,
    partial: EnrichedContact,
) -> CandidateContact:
    """
    Return a new CandidateContact with fields from partial enrichment
    filled in, so subsequent providers can build on this data.
    """
    return original.model_copy(
        update={
            "email": partial.email or original.email,
            "phone": partial.phone or original.phone,
            "linkedin_url": partial.linkedin_url or original.linkedin_url,
        }
    )

