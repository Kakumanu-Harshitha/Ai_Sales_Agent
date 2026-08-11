"""
providers/serper_provider.py - Serper.dev Google Places discovery.

Uses Serper.dev Places API to query Google Maps for local businesses.
Provides dense, highly accurate contact info (phone, website, address)
for local clinics.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.exceptions import (
    ProviderResponseError,
    ProviderTimeoutError,
)
from apps.api.modules.prospecting.engine.providers.base import LeadDiscoveryProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    ICPFilter,
    ProviderName,
)

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.SERPER

class SerperProvider(LeadDiscoveryProvider):
    """Discovers companies via Serper.dev Google Places API."""

    def __init__(self) -> None:
        self.settings = get_settings()

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return bool(self.settings.serper_api_key)

    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        if not self.is_enabled:
            return []

        # Build search query
        keywords = " ".join(icp.keywords) if icp.keywords else "healthcare clinic"
        location = "United States"
        if icp.regions:
            location = " ".join(icp.regions)
        
        query = f"{keywords} in {location}"

        url = "https://google.serper.dev/places"
        headers = {
            "X-API-KEY": self.settings.serper_api_key or "",
            "Content-Type": "application/json"
        }
        payload = {
            "q": query,
            "gl": "us"
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as e:
            raise ProviderTimeoutError(f"Serper timeout: {e}") from e
        except httpx.HTTPError as e:
            logger.warning("Serper request failed: %s", e)
            return []
        except Exception as e:
            logger.error("Serper error: %s", e)
            return []

        places = data.get("places", [])
        companies: list[CandidateCompany] = []

        for place in places:
            # We want places that have at least a website or phone
            name = place.get("title")
            website = place.get("website")
            phone = place.get("phoneNumber")
            address = place.get("address")
            
            if not name:
                continue

            companies.append(
                CandidateCompany(
                    name=name,
                    domain=self._extract_domain(website) if website else None,
                    website=website,
                    industry="Healthcare",
                    description=place.get("category", ""),
                    address=address,
                    phone=phone,
                    confidence_score=90 if (website or phone) else 50,
                    source_provider=PROVIDER,
                    raw_data={"serper_place": place}
                )
            )

        return companies

    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        import urllib.parse
        try:
            parsed = urllib.parse.urlparse(url)
            netloc = parsed.netloc
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return url

    async def search_contacts(self, company: CandidateCompany, target_roles: list[str]) -> list[CandidateContact]:
        # Google Places doesn't provide granular employee contacts, so this returns empty.
        return []
