"""
providers/base.py â€” Abstract base classes for the provider interface.

These ABCs are the contract that every discovery and enrichment provider
must implement. Adding a new provider means:
  1. Create a new file in providers/
  2. Implement the relevant ABC
  3. Register it in the provider list in config or the service layer

Zero changes to existing code are required.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    EnrichedContact,
    ICPFilter,
    ProviderName,
)


class LeadDiscoveryProvider(ABC):
    """
    Contract for any company and contact discovery source.

    All methods are async. Implementations must raise the appropriate
    subclass of ProviderError on failure (defined in core/exceptions.py)
    so the service layer can handle them uniformly.
    """

    @property
    @abstractmethod
    def name(self) -> ProviderName:
        """Unique identifier for this provider (used in logging and lead_sources table)."""

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """
        Return True if this provider is properly configured and ready to use.

        A provider whose API key is absent must return False here.
        The service layer will skip disabled providers without logging an error.
        """

    @abstractmethod
    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        """
        Discover companies matching the given ICP criteria.

        Args:
            icp: Ideal Customer Profile filter criteria.

        Returns:
            List of CandidateCompany objects (may be empty).

        Raises:
            ProviderAuthError: Key is invalid.
            ProviderQuotaExhaustedError: Free-tier limit reached.
            ProviderRateLimitError: Temporary rate limit (should retry).
            ProviderTimeoutError: Request timed out.
            ProviderResponseError: Unexpected response format.
        """

    @abstractmethod
    async def search_contacts(
        self, company: CandidateCompany, target_roles: list[str]
    ) -> list[CandidateContact]:
        """
        Discover decision makers at a specific company.

        Args:
            company: The company to find contacts for.
            target_roles: List of role titles to search for.

        Returns:
            List of CandidateContact objects (may be empty).
        """


class EnrichmentProvider(ABC):
    """
    Contract for any contact enrichment and email resolution source.
    """

    @property
    @abstractmethod
    def name(self) -> ProviderName:
        """Unique identifier for this enrichment provider."""

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """True if this provider is configured and ready."""

    @abstractmethod
    async def enrich_contact(
        self,
        contact: CandidateContact,
        company_domain: str | None,
    ) -> EnrichedContact:
        """
        Attempt to resolve email, phone, and social profiles for a contact.

        Args:
            contact: The contact to enrich.
            company_domain: The company's web domain (aids email resolution).

        Returns:
            An EnrichedContact â€” some fields may still be None if the provider
            had no data. Never raises on 'not found' â€” only on auth/rate errors.
        """

