"""
providers/hunter_provider.py â€” Hunter.io email enrichment provider.

Hunter.io is used for:
  1. Domain Search â€” find all emails associated with a company domain.
  2. Email Finder â€” find a specific person's email given name + domain.
  3. Email Verifier â€” verify whether an email address is deliverable.

Graceful degradation:
  - is_enabled returns False when HUNTER_API_KEY is absent.
  - 401 â†’ ProviderAuthError
  - 429 / quota exceeded â†’ ProviderQuotaExhaustedError
  - No result found â†’ returns EnrichedContact with enrichment_status=PARTIAL
    (never raises on 'not found')

Hunter is the primary enrichment provider. Apollo is the fallback.
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

PROVIDER = ProviderName.HUNTER


class HunterProvider(EnrichmentProvider):
    """
    Hunter.io adapter for email discovery and enrichment.
    Implements EnrichmentProvider only (not a discovery source).
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._base_url = self._settings.hunter_base_url
        self._timeout = self._settings.provider_timeout_seconds

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return self._settings.hunter_enabled

    async def enrich_contact(
        self,
        contact: CandidateContact,
        company_domain: str | None,
    ) -> EnrichedContact:
        """
        Attempt to resolve email for a contact using Hunter.io.

        Strategy:
          1. If domain is known and contact has a name â†’ use Email Finder.
          2. If domain is known but no name â†’ use Domain Search and return
             the best matching role.
          3. If we already have an email â†’ run Email Verifier on it.
        """
        if not self.is_enabled:
            return _passthrough(contact)

        email: str | None = None
        email_status = VerificationStatus.UNVERIFIED

        # Case 1: we have name + domain â†’ use Email Finder
        if company_domain and contact.first_name and contact.last_name:
            found, verified = await self._find_email(
                contact.first_name, contact.last_name, company_domain
            )
            if found:
                email = found
                email_status = (
                    VerificationStatus.VERIFIED
                    if verified
                    else VerificationStatus.UNVERIFIED
                )

        # Case 2: we have an existing email â†’ verify it
        elif contact.email:
            verified = await self._verify_email(contact.email)
            email = contact.email
            email_status = (
                VerificationStatus.VERIFIED if verified else VerificationStatus.UNVERIFIED
            )

        # Case 3: domain search as last resort
        elif company_domain:
            email = await self._domain_search_first_result(
                company_domain, contact.title
            )

        final_email = email or contact.email
        has_email = bool(final_email)

        return EnrichedContact(
            source_contact=contact,
            email=final_email,
            email_verification_status=email_status if final_email else VerificationStatus.UNVERIFIED,
            phone=contact.phone,
            phone_verification_status=VerificationStatus.UNVERIFIED,
            linkedin_url=contact.linkedin_url,
            enrichment_status=(
                EnrichmentStatus.FULL if has_email else EnrichmentStatus.PARTIAL
            ),
            enrichment_providers_used=[PROVIDER],
        )

    # â”€â”€â”€ Hunter API Methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _find_email(
        self, first_name: str, last_name: str, domain: str
    ) -> tuple[str | None, bool]:
        """
        Email Finder: find a specific person's email.
        Returns (email, is_verified).
        """
        params = {
            "first_name": first_name,
            "last_name": last_name,
            "domain": domain,
            "api_key": self._settings.hunter_api_key,
        }

        try:
            data = await self._get("/email-finder", params)
        except (ProviderQuotaExhaustedError, ProviderAuthError):
            raise
        except Exception as exc:
            logger.debug("Hunter email-finder failed: %s", exc)
            return None, False

        result = (data.get("data") or {})
        email = result.get("email")
        confidence = result.get("score", 0)
        verified = result.get("verification", {}).get("status") == "valid"

        if email and confidence >= 70:
            return email, verified

        return None, False

    async def _verify_email(self, email: str) -> bool:
        """Email Verifier: check if an email is deliverable."""
        params = {
            "email": email,
            "api_key": self._settings.hunter_api_key,
        }

        try:
            data = await self._get("/email-verifier", params)
        except Exception:
            return False

        result = data.get("data") or {}
        return result.get("status") in ("valid", "accept_all", "webmail")

    async def _domain_search_first_result(
        self, domain: str, role_hint: str | None
    ) -> str | None:
        """
        Domain Search: find all emails at a domain and return the best match
        for the target role.
        """
        params = {
            "domain": domain,
            "type": "personal",
            "api_key": self._settings.hunter_api_key,
        }

        try:
            data = await self._get("/domain-search", params)
        except Exception:
            return None

        emails = (data.get("data") or {}).get("emails") or []
        if not emails:
            return None

        # Prefer emails whose position matches the role hint
        if role_hint:
            hint_lower = role_hint.lower()
            for item in emails:
                position = (item.get("position") or "").lower()
                if any(w in position for w in hint_lower.split() if len(w) > 3):
                    return item.get("value")

        # Fall back to highest-confidence email
        best = max(emails, key=lambda e: e.get("confidence", 0), default=None)
        return best.get("value") if best else None

    # â”€â”€â”€ HTTP Helper â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    async def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"

        cache_key = f"hunter_{path}_{hash(frozenset([(k, v) for k, v in params.items() if k != 'api_key']))}"
        cached = api_response_cache.get(cache_key)
        if cached:
            logger.debug(f"Hunter cache hit for {path}")
            return cached

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, str(exc)) from exc

        if response.status_code == 200:
            try:
                data = response.json()
                api_response_cache.set(cache_key, data)
                return data
            except Exception as exc:
                raise ProviderResponseError(PROVIDER.value, f"Invalid JSON: {exc}") from exc

        if response.status_code == 401:
            raise ProviderAuthError(PROVIDER.value, "Invalid Hunter.io API key.")

        if response.status_code in (402, 429):
            raise ProviderQuotaExhaustedError(
                PROVIDER.value,
                "Hunter.io quota exhausted. Falling back to Apollo enrichment.",
            )

        raise ProviderResponseError(
            PROVIDER.value,
            f"HTTP {response.status_code}: {response.text[:200]}",
        )


def _passthrough(contact: CandidateContact) -> EnrichedContact:
    """Return EnrichedContact preserving whatever the contact already had."""
    from apps.api.modules.prospecting.engine.schemas.internal import EnrichedContact, EnrichmentStatus
    return EnrichedContact(
        source_contact=contact,
        email=contact.email,
        phone=contact.phone,
        linkedin_url=contact.linkedin_url,
        enrichment_status=EnrichmentStatus.PARTIAL,
        enrichment_providers_used=[],
    )

