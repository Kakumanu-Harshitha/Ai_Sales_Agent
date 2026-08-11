"""
providers/prospeo_provider.py - Prospeo.io email enrichment provider.
"""

from __future__ import annotations

import logging

import httpx

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
)
from apps.api.modules.prospecting.engine.providers.base import EnrichmentProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateContact,
    EnrichedContact,
    EnrichmentStatus,
    ProviderName,
    VerificationStatus,
)

logger = logging.getLogger(__name__)

PROVIDER = ProviderName("prospeo") if "prospeo" in [v.value for v in ProviderName] else ProviderName.MANUAL

class ProspeoProvider(EnrichmentProvider):
    def __init__(self) -> None:
        self._settings = get_settings()
        self._api_key = getattr(self._settings, "prospeo_api_key", None)
        self._base_url = "https://api.prospeo.io"
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return bool(self._api_key)

    async def enrich_contact(
        self, contact: CandidateContact, company_domain: str | None
    ) -> EnrichedContact:
        if not self.is_enabled or not company_domain or not contact.first_name:
            return self._passthrough(contact)

        email = None
        status = VerificationStatus.UNVERIFIED

        payload = {
            "first_name": contact.first_name,
            "last_name": contact.last_name or "",
            "company": company_domain,
        }

        try:
            headers = {
                "X-KEY": self._api_key,
                "Content-Type": "application/json"
            }
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/email-finder",
                    json=payload,
                    headers=headers
                )

            if response.status_code == 200:
                data = response.json()
                email = data.get("response", {}).get("email") or data.get("email")
                if email:
                    status = VerificationStatus.VERIFIED
            elif response.status_code in (401, 403):
                raise ProviderAuthError(self.name.value, "Invalid Prospeo API key.")
            elif response.status_code == 429:
                raise ProviderQuotaExhaustedError(self.name.value, "Prospeo quota exhausted.")
        except Exception as exc:
            if isinstance(exc, (ProviderAuthError, ProviderQuotaExhaustedError)):
                raise
            logger.debug("Prospeo error: %s", exc)

        final_email = email or contact.email
        has_email = bool(final_email)

        return EnrichedContact(
            source_contact=contact,
            email=final_email,
            email_verification_status=status if email else VerificationStatus.UNVERIFIED,
            phone=contact.phone,
            phone_verification_status=VerificationStatus.UNVERIFIED,
            linkedin_url=contact.linkedin_url,
            enrichment_status=EnrichmentStatus.FULL if has_email else EnrichmentStatus.PARTIAL,
            enrichment_providers_used=[self.name] if email else [],
        )

    def _passthrough(self, contact: CandidateContact) -> EnrichedContact:
        from apps.api.modules.prospecting.engine.schemas.internal import EnrichedContact, EnrichmentStatus
        return EnrichedContact(
            source_contact=contact,
            email=contact.email,
            phone=contact.phone,
            linkedin_url=contact.linkedin_url,
            enrichment_status=EnrichmentStatus.PARTIAL,
            enrichment_providers_used=[],
        )
