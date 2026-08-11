"""
providers/overpass_provider.py — OpenStreetMap Overpass API healthcare discovery.

Replaces BizDataProvider with direct Overpass API queries which offer:
  - 100% free, no API key required
  - Full range of OSM healthcare amenity types (clinic, hospital, dentist, etc.)
  - Proper bounding-box geographic search from ICP regions
  - Randomized amenity selection per run so same-ICP searches surface variety

Overpass API fair-use policy:
  - We use a low timeout + minimal results to be a good citizen
  - We include a User-Agent header identifying our app
  - Results are cached to avoid repeat queries within the same session
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
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
from apps.api.core.cache import api_response_cache

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.OVERPASS

# Overpass API endpoints — rotate between official and community mirrors
_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.ch/api/interpreter",
]

# Full list of OSM healthcare amenity/tag combinations we can query
# Each entry: (osm_key, osm_value, friendly_name)
_ALL_HEALTHCARE_TAGS: list[tuple[str, str, str]] = [
    ("amenity", "hospital", "hospital"),
    ("amenity", "clinic", "clinic"),
    ("amenity", "doctors", "doctors office"),
    ("amenity", "dentist", "dental clinic"),
    ("amenity", "pharmacy", "pharmacy"),
    ("amenity", "nursing_home", "nursing home"),
    ("amenity", "social_facility", "social facility"),
    ("healthcare", "hospital", "hospital"),
    ("healthcare", "clinic", "clinic"),
    ("healthcare", "centre", "health centre"),
    ("healthcare", "physiotherapist", "physiotherapy"),
    ("healthcare", "psychotherapist", "mental health"),
    ("healthcare", "laboratory", "laboratory"),
    ("healthcare", "rehabilitation", "rehabilitation"),
    ("healthcare", "urgent_care", "urgent care"),
    ("healthcare", "dialysis", "dialysis centre"),
    ("amenity", "veterinary", "veterinary"),
]

# ICP keyword → relevant OSM tags to prioritize
_KEYWORD_TAG_MAP: dict[str, list[str]] = {
    "hospital": ["hospital"],
    "clinic": ["clinic", "doctors office", "health centre"],
    "dental": ["dental clinic"],
    "dentist": ["dental clinic"],
    "pharmacy": ["pharmacy"],
    "rehab": ["rehabilitation", "physiotherapy"],
    "mental": ["mental health"],
    "urgent": ["urgent care"],
    "nursing": ["nursing home"],
    "lab": ["laboratory"],
    "dialysis": ["dialysis centre"],
    "vet": ["veterinary"],
    "veterinary": ["veterinary"],
    "physiotherapy": ["physiotherapy"],
}

# Geocoding API for converting city/state names to bounding boxes
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Results per Overpass query
_MAX_RESULTS_PER_QUERY = 25

# Default US bounding box if geocoding fails (continental US)
_US_BBOX = (24.396308, -125.0, 49.384358, -66.93457)


class OverpassProvider(LeadDiscoveryProvider):
    """
    Discovers local healthcare businesses via the Overpass API (OpenStreetMap).

    Always enabled — no API key required.
    Randomizes the subset of amenity tags queried so identical ICP runs
    surface different results over time.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._timeout = min(self._settings.provider_timeout_seconds, 20)

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return True  # Always available — no auth required

    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        """
        Discover healthcare businesses via Overpass API.

        Strategy:
          1. Resolve ICP regions to bounding boxes via Nominatim geocoding.
          2. Select a randomized subset of relevant OSM amenity tags based on ICP.
          3. Query Overpass for each (bbox, tag) combination concurrently.
          4. Parse results into CandidateCompany objects.
        """
        bboxes = await self._resolve_bboxes(icp)
        tags = self._select_tags(icp)

        logger.info(
            "Overpass: querying %d bounding boxes × %d tag types",
            len(bboxes), len(tags),
        )

        tasks = []
        
        # Overpass allows very few concurrent connections per IP.
        # We strictly limit it to 1 concurrent request and add a delay
        # to ensure we don't get 429 Too Many Requests.
        sem = asyncio.Semaphore(1)
        
        async def _query_with_sem(bbox_param, tags_param):
            async with sem:
                ep = random.choice(_OVERPASS_ENDPOINTS)
                result = await self._query_overpass(ep, bbox_param, tags_param)
                # Strict sleep to respect Overpass rate limits
                await asyncio.sleep(2.0)
                return result

        # Max 6 tag types per region to avoid overly complex queries
        tags_to_query = tags[:6]

        for bbox in bboxes[:3]:  # Max 3 regions
            tasks.append(_query_with_sem(bbox, tags_to_query))

        results_per_task = await asyncio.gather(*tasks, return_exceptions=True)

        seen_keys: set[str] = set()
        companies: list[CandidateCompany] = []

        for result in results_per_task:
            if isinstance(result, Exception):
                logger.warning("Overpass task failed: %s", result)
                continue
            for element in result:
                company = _parse_element(element, icp)
                if company is None:
                    continue
                dedup_key = (
                    company.domain
                    or f"{company.name.lower().strip()}|{company.hq_city or ''}|{company.hq_state or ''}"
                )
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)
                companies.append(company)

        logger.info("Overpass: discovered %d unique healthcare businesses", len(companies))
        return companies

    async def search_contacts(
        self, company: CandidateCompany, target_roles: list[str]
    ) -> list[CandidateContact]:
        # Overpass does not provide contact-level data
        return []

    def _select_tags(self, icp: ICPFilter) -> list[tuple[str, str, str]]:
        """
        Select relevant OSM tags based on ICP keywords/industries.
        Randomizes order within relevance groups for result variety.
        """
        relevant_names: set[str] = set()

        # Match ICP terms to known tag friendly names
        all_terms = [t.lower() for t in icp.industries + icp.keywords]
        for term in all_terms:
            for keyword, names in _KEYWORD_TAG_MAP.items():
                if keyword in term:
                    relevant_names.update(names)

        # Build prioritized list: relevant first, rest randomly shuffled after
        relevant_tags = [t for t in _ALL_HEALTHCARE_TAGS if t[2] in relevant_names]
        other_tags = [t for t in _ALL_HEALTHCARE_TAGS if t[2] not in relevant_names]
        random.shuffle(other_tags)

        return relevant_tags + other_tags

    async def _resolve_bboxes(
        self, icp: ICPFilter
    ) -> list[tuple[float, float, float, float]]:
        """
        Convert ICP region strings to (south, west, north, east) bounding boxes.
        Falls back to US bounding box if geocoding fails or regions are generic.
        """
        bboxes = []
        skip_terms = {"us", "usa", "united states", "america", "canada", "ca"}

        regions = [r for r in icp.regions if r.lower().strip() not in skip_terms]

        async with httpx.AsyncClient(
            timeout=8,
            headers={"User-Agent": "SETV-ProspectingAgent/1.0 (healthcare lead gen)"},
        ) as client:
            for region in regions[:3]:
                bbox = await self._geocode_region(client, region)
                if bbox:
                    bboxes.append(bbox)

        if not bboxes:
            logger.debug("Overpass: no regions geocoded — using continental US bbox")
            bboxes.append(_US_BBOX)

        return bboxes

    async def _geocode_region(
        self, client: httpx.AsyncClient, region: str
    ) -> tuple[float, float, float, float] | None:
        """Use Nominatim to get the bounding box for a region string."""
        cache_key = f"nominatim_bbox_{region.lower().strip()}"
        cached = api_response_cache.get(cache_key)
        if cached:
            return tuple(cached)  # type: ignore[return-value]

        try:
            response = await client.get(
                _NOMINATIM_URL,
                params={
                    "q": region,
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 0,
                },
            )
            if response.status_code != 200:
                return None
            data = response.json()
            if not data:
                return None
            item = data[0]
            bbox_raw = item.get("boundingbox")
            if not bbox_raw or len(bbox_raw) < 4:
                return None
            # Nominatim returns [south, north, west, east]
            south, north, west, east = (float(x) for x in bbox_raw)
            result = (south, west, north, east)
            api_response_cache.set(cache_key, list(result))
            return result
        except Exception as exc:
            logger.debug("Nominatim geocoding failed for '%s': %s", region, exc)
            return None

    async def _query_overpass(
        self,
        endpoint: str,
        bbox: tuple[float, float, float, float],
        tags: list[tuple[str, str, str]],
    ) -> list[dict[str, Any]]:
        """Query Overpass API for multiple tag types within a bounding box in a single request."""
        south, west, north, east = bbox
        bbox_str = f"{south},{west},{north},{east}"

        # Build union query for all tags
        tag_queries = []
        for tag_key, tag_val, _ in tags:
            tag_queries.append(f'  node["{tag_key}"="{tag_val}"]({bbox_str});')
            tag_queries.append(f'  way["{tag_key}"="{tag_val}"]({bbox_str});')
        
        tag_query_str = "\n".join(tag_queries)

        # Overpass QL — query nodes, ways, relations with the given tags
        query = (
            f'[out:json][timeout:15];\n'
            f'(\n{tag_query_str}\n);\n'
            f'out body center {_MAX_RESULTS_PER_QUERY};'
        )

        # Create a hash of the tags for the cache key to keep it short
        tags_hash = "_".join([f"{k}={v}" for k, v, _ in tags])
        import hashlib
        tags_hash = hashlib.md5(tags_hash.encode()).hexdigest()[:8]

        cache_key = f"overpass_multi_{tags_hash}_{bbox_str}"
        cached = api_response_cache.get(cache_key)
        if cached is not None:
            logger.debug("Overpass cache hit: multi-tag in %s", bbox_str)
            return cached

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={"User-Agent": "SETV-ProspectingAgent/1.0 (healthcare lead gen)"},
            ) as client:
                response = await client.post(endpoint, data={"data": query})
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, repr(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, repr(exc)) from exc

        if response.status_code != 200:
            raise ProviderResponseError(
                PROVIDER.value, f"HTTP {response.status_code}: {response.text[:200]}"
            )

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderResponseError(PROVIDER.value, f"Invalid JSON: {exc}") from exc

        elements = data.get("elements", [])
        api_response_cache.set(cache_key, elements)
        logger.debug(
            "Overpass: %d elements for %s=%s in bbox %s",
            len(elements), tag_key, tag_val, bbox_str,
        )
        return elements


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_element(
    element: dict[str, Any], icp: ICPFilter
) -> CandidateCompany | None:
    """Convert an Overpass API element to a CandidateCompany."""
    tags = element.get("tags", {})

    name = tags.get("name") or tags.get("official_name") or tags.get("alt_name")
    if not name or len(name.strip()) < 2:
        return None

    # Skip elements that are clearly not businesses (just tagged land areas etc.)
    if element.get("type") == "relation" and not tags.get("name"):
        return None

    website = tags.get("website") or tags.get("contact:website") or tags.get("url")
    phone = (
        tags.get("phone")
        or tags.get("contact:phone")
        or tags.get("contact:mobile")
    )

    # Extract domain from website
    domain: str | None = None
    if website:
        match = re.search(r"(?:https?://)?(?:www\.)?([^/\s]+)", website)
        if match:
            raw = match.group(1).lower().strip(".")
            if "." in raw and len(raw) > 3:
                domain = raw

    # Location from OSM tags
    city = tags.get("addr:city") or tags.get("is_in:city")
    state = tags.get("addr:state") or tags.get("is_in:state")
    postcode = tags.get("addr:postcode")
    street = tags.get("addr:street")
    housenumber = tags.get("addr:housenumber")

    address_parts = [p for p in [housenumber, street, city, state, postcode] if p]
    full_address = ", ".join(address_parts) if address_parts else None

    # Infer center lat/lon for way elements
    center = element.get("center", {})
    lat = element.get("lat") or center.get("lat")
    lon = element.get("lon") or center.get("lon")

    # Build description from available tags
    amenity_type = (
        tags.get("healthcare")
        or tags.get("amenity")
        or tags.get("operator_type")
        or "healthcare"
    )
    description_parts = [f"Type: {amenity_type}"]
    if full_address:
        description_parts.append(f"Address: {full_address}")
    if phone:
        description_parts.append(f"Phone: {phone}")
    description = " | ".join(description_parts)

    industry = icp.industries[0] if icp.industries else "Healthcare"

    return CandidateCompany(
        name=str(name).strip(),
        domain=domain,
        website=website,
        industry=industry,
        hq_city=city,
        hq_state=state,
        hq_country="US",
        description=description,
        source_provider=PROVIDER,
        raw_payload={
            "osm_id": element.get("id"),
            "osm_type": element.get("type"),
            "lat": lat,
            "lon": lon,
            "tags": tags,
            "phone": phone,
        },
    )
