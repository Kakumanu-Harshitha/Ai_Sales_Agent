"""
services/company_discovery.py â€” CompanyDiscoveryService.

Responsibility: Fan out to all registered providers, collect company
candidates, and return a merged (undeduped) list.

This service:
  - Iterates providers in priority order (Apollo first).
  - Catches and logs provider-level errors without crashing.
  - Skips disabled providers silently.
  - Stops adding results once max_results is reached.
  - Tracks per-provider stats for the job status response.

It does NOT deduplicate â€” that is DeduplicationService's responsibility.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from apps.api.modules.prospecting.engine.core.cache import get_cache
from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderAuthError,
    ProviderQuotaExhaustedError,
    ProviderRateLimitError,
    ProviderTimeoutError,
)
from apps.api.modules.prospecting.engine.providers.base import LeadDiscoveryProvider
from apps.api.modules.prospecting.engine.schemas.internal import CandidateCompany, ICPFilter

logger = logging.getLogger(__name__)


@dataclass
class DiscoveryStats:
    """Per-provider discovery statistics for job status reporting."""
    discovered: int = 0
    skipped: bool = False
    skip_reason: str | None = None
    cache_hit: bool = False
    errors: list[str] = field(default_factory=list)


class CompanyDiscoveryService:
    """
    Orchestrates company discovery across multiple providers.

    Providers are tried in registration order. Each provider failure is
    handled gracefully â€” the service continues with remaining providers.
    """

    def __init__(self, providers: list[LeadDiscoveryProvider]) -> None:
        """
        Args:
            providers: Ordered list of discovery providers.
                       First provider is considered primary (Apollo).
        """
        self._providers = providers

    async def discover(
        self, icp: ICPFilter
    ) -> tuple[list[CandidateCompany], dict[str, DiscoveryStats]]:
        """
        Discover companies from all providers.

        Returns:
            (companies, stats_by_provider)
            - companies: merged list of CandidateCompany objects (not deduped)
            - stats_by_provider: per-provider stats dict for job status
        """
        all_companies: list[CandidateCompany] = []
        stats: dict[str, DiscoveryStats] = {}

        import random
        providers_to_try = list(self._providers)
        random.shuffle(providers_to_try)

        for provider in providers_to_try:
            provider_stats = DiscoveryStats()
            stats[provider.name.value] = provider_stats

            # Skip disabled providers silently
            if not provider.is_enabled:
                provider_stats.skipped = True
                provider_stats.skip_reason = "Provider not configured (missing API key)"
                logger.debug("Provider '%s' is disabled â€” skipping", provider.name.value)
                continue

            # Stop if we already have enough candidates
            if len(all_companies) >= icp.max_results * 2:
                provider_stats.skipped = True
                provider_stats.skip_reason = "Sufficient candidates already discovered"
                break

            try:
                cache = get_cache()
                cache_key = cache.make_key(
                    provider.name.value,
                    {"method": "search_companies", "icp": icp.model_dump()}
                )

                companies = cache.get(cache_key)
                if companies is not None:
                    provider_stats.cache_hit = True
                    logger.info(
                        "Provider '%s': CACHE HIT (returned %d companies)",
                        provider.name.value, len(companies),
                    )
                else:
                    logger.info("Running company discovery via '%s'", provider.name.value)
                    companies = await provider.search_companies(icp)
                    cache.set(cache_key, companies)
                    logger.info(
                        "Provider '%s': returned %d companies",
                        provider.name.value, len(companies),
                    )

                provider_stats.discovered = len(companies)
                all_companies.extend(companies)

            except ProviderAuthError as exc:
                msg = f"Authentication failure â€” check API key: {exc}"
                logger.error("Provider '%s': %s", provider.name.value, msg)
                provider_stats.errors.append(msg)

            except ProviderQuotaExhaustedError as exc:
                msg = f"Quota exhausted â€” continuing with remaining providers: {exc}"
                logger.warning("Provider '%s': %s", provider.name.value, msg)
                provider_stats.errors.append(msg)

            except ProviderRateLimitError as exc:
                msg = f"Rate limited â€” skipping for this run: {exc}"
                logger.warning("Provider '%s': %s", provider.name.value, msg)
                provider_stats.errors.append(msg)

            except ProviderTimeoutError as exc:
                msg = f"Request timed out: {exc}"
                logger.warning("Provider '%s': %s", provider.name.value, msg)
                provider_stats.errors.append(msg)

            except Exception as exc:
                msg = f"Unexpected error: {exc}"
                logger.error(
                    "Provider '%s': unexpected error â€” %s",
                    provider.name.value, exc, exc_info=True,
                )
                provider_stats.errors.append(msg)

        total = len(all_companies)
        logger.info(
            "Company discovery complete: %d total candidates from %d providers",
            total, len(self._providers),
        )
        return all_companies, stats

