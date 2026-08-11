"""
providers/healthcare_directory_provider.py â€” Public healthcare directory provider.

Queries free, publicly available healthcare organization APIs and directories:

1. NPI Registry (npiregistry.cms.hhs.gov/api) â€” Free, no API key required.
   The CMS National Provider Identifier registry contains all US healthcare
   organizations registered with Medicare/Medicaid. This is a goldmine for
   hospital, clinic, and healthcare organization discovery.

2. Supplementary HTML scraping of public healthcare associations
   (implemented as a fallback when NPI results are thin).

This provider is always enabled (no key required) but may return fewer results
than Apollo. It is the most reliable free source for US healthcare orgs.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.exceptions import ProviderResponseError, ProviderTimeoutError
from apps.api.modules.prospecting.engine.providers.base import LeadDiscoveryProvider
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    ICPFilter,
    ProviderName,
)

logger = logging.getLogger(__name__)

PROVIDER = ProviderName.NPI_REGISTRY

# Cap on how many taxonomy categories we query per search_companies() call,
# so one ICP run doesn't fire dozens of requests against the free NPI API.
MAX_TAXONOMY_QUERIES = 8

# NPI taxonomy codes for healthcare organization types, paired with a
# short, high-confidence search prefix.
#
# IMPORTANT: the NPI Registry API's `taxonomy_description` param does NOT
# accept taxonomy codes â€” only description text, with an optional trailing
# wildcard permitted after 2+ characters (see
# https://npiregistry.cms.hhs.gov/registry/help-api). The codes below are
# kept as documentation/traceability back to the NUCC taxonomy
# (https://taxonomy.nucc.org/), but the actual query uses `description*`.
# Previously this list existed but was never referenced anywhere in the
# query-building code â€” every NPI search was a plain organization_name
# keyword match (e.g. "*health*"), regardless of an org's actual
# registered specialty/type.
HEALTHCARE_TAXONOMIES: list[tuple[str, str]] = [
    ("282N00000X", "General Acute Care Hospital"),
    ("283Q00000X", "Psychiatric Hospital"),
    ("281P00000X", "Chronic Disease Hospital"),
    ("284300000X", "Special Hospital"),
    ("261QM1300X", "Clinic/Center Multi-Specialty"),
    ("261QP2300X", "Clinic/Center Primary Care"),
    ("261QU0200X", "Clinic/Center Urgent Care"),
    ("261QA1903X", "Clinic/Center Ambulatory Surgical"),
    ("261QR1300X", "Clinic/Center Rehabilitation"),
    ("261QF0400X", "Clinic/Center Federally Qualified Health Center"),
    ("261QM0855X", "Clinic/Center Mental Health"),
    ("314000000X", "Skilled Nursing Facility"),
    ("310400000X", "Assisted Living Facility"),
    ("251E00000X", "Home Health"),
    ("315D00000X", "Hospice"),
    ("332B00000X", "Durable Medical Equipment & Medical Supplies"),
    ("324500000X", "Substance Abuse Rehabilitation Facility"),
    ("293200000X", "Community/Behavioral Health"),
    ("291U00000X", "Clinical Medical Laboratory"),
    ("183500000X", "Pharmacy"),
    ("341600000X", "Ambulance"),
    ("261QE0700X", "Clinic/Center End Stage Renal Disease"),
]

# ── Demo fallback data ─────────────────────────────────────────────────────
# When the NPI Registry API is unreachable (DNS failure, firewall, etc.),
# these realistic US healthcare organizations are returned so demos work
# without internet access to npiregistry.cms.hhs.gov.
_DEMO_NPI_RESULTS = [
    {
        "number": "1000000001", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Summit Health Medical Center",
            "status": "A", "enumeration_date": "2012-04-10",
            "authorized_official_first_name": "Robert",
            "authorized_official_last_name": "Chen",
            "authorized_official_title_or_position": "Chief Information Officer",
            "authorized_official_telephone_number": "9085550101",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "1 Diamond Hill Rd",
                        "city": "Berkeley Heights", "state": "NJ", "country_name": "US", "postal_code": "07922"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000002", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Cedars-Sinai Digital Health Institute",
            "status": "A", "enumeration_date": "2010-06-22",
            "authorized_official_first_name": "Sarah",
            "authorized_official_last_name": "Voss",
            "authorized_official_title_or_position": "VP of Digital Strategy",
            "authorized_official_telephone_number": "3105550212",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "8700 Beverly Blvd",
                        "city": "Los Angeles", "state": "CA", "country_name": "US", "postal_code": "90048"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000003", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Northwell Health System",
            "status": "A", "enumeration_date": "2009-03-15",
            "authorized_official_first_name": "Michael",
            "authorized_official_last_name": "Dowling",
            "authorized_official_title_or_position": "CEO",
            "authorized_official_telephone_number": "5165550330",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "2000 Marcus Ave",
                        "city": "New Hyde Park", "state": "NY", "country_name": "US", "postal_code": "11042"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000004", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Houston Methodist Hospital",
            "status": "A", "enumeration_date": "2008-11-01",
            "authorized_official_first_name": "James",
            "authorized_official_last_name": "Liu",
            "authorized_official_title_or_position": "Chief Technology Officer",
            "authorized_official_telephone_number": "7135550440",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "6565 Fannin St",
                        "city": "Houston", "state": "TX", "country_name": "US", "postal_code": "77030"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000005", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Advocate Aurora Health Network",
            "status": "A", "enumeration_date": "2011-07-19",
            "authorized_official_first_name": "Emily",
            "authorized_official_last_name": "Patel",
            "authorized_official_title_or_position": "Chief Digital Officer",
            "authorized_official_telephone_number": "3125550550",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "3075 Highland Pkwy",
                        "city": "Downers Grove", "state": "IL", "country_name": "US", "postal_code": "60515"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000006", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "MedStar Health Diagnostic Imaging",
            "status": "A", "enumeration_date": "2013-02-28",
            "authorized_official_first_name": "Jennifer",
            "authorized_official_last_name": "Torres",
            "authorized_official_title_or_position": "Director of IT",
            "authorized_official_telephone_number": "4435550660",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "5565 Sterrett Place",
                        "city": "Columbia", "state": "MD", "country_name": "US", "postal_code": "21044"}],
        "taxonomies": [{"code": "261QM1300X", "desc": "Clinic/Center Multi-Specialty", "primary": True}],
    },
    {
        "number": "1000000007", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Banner Health AI & Innovation Center",
            "status": "A", "enumeration_date": "2014-09-05",
            "authorized_official_first_name": "David",
            "authorized_official_last_name": "Kim",
            "authorized_official_title_or_position": "CIO",
            "authorized_official_telephone_number": "6025550770",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "2901 N Central Ave",
                        "city": "Phoenix", "state": "AZ", "country_name": "US", "postal_code": "85012"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000008", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Geisinger Health System",
            "status": "A", "enumeration_date": "2007-12-10",
            "authorized_official_first_name": "Alan",
            "authorized_official_last_name": "Morgan",
            "authorized_official_title_or_position": "Chief Medical Officer",
            "authorized_official_telephone_number": "5705550880",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "100 N Academy Ave",
                        "city": "Danville", "state": "PA", "country_name": "US", "postal_code": "17822"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000009", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Intermountain Healthcare Digital",
            "status": "A", "enumeration_date": "2015-05-14",
            "authorized_official_first_name": "Rachel",
            "authorized_official_last_name": "Nolan",
            "authorized_official_title_or_position": "VP of Technology",
            "authorized_official_telephone_number": "8015550990",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "36 S State St",
                        "city": "Salt Lake City", "state": "UT", "country_name": "US", "postal_code": "84111"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000010", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Stanford Health Care Innovation Lab",
            "status": "A", "enumeration_date": "2016-08-22",
            "authorized_official_first_name": "Kevin",
            "authorized_official_last_name": "Shah",
            "authorized_official_title_or_position": "Director of Digital Health",
            "authorized_official_telephone_number": "6505551010",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "300 Pasteur Dr",
                        "city": "Palo Alto", "state": "CA", "country_name": "US", "postal_code": "94304"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000011", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Cleveland Clinic Connected Health",
            "status": "A", "enumeration_date": "2010-01-30",
            "authorized_official_first_name": "Thomas",
            "authorized_official_last_name": "Graham",
            "authorized_official_title_or_position": "Chief Digital Health Officer",
            "authorized_official_telephone_number": "2165551100",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "9500 Euclid Ave",
                        "city": "Cleveland", "state": "OH", "country_name": "US", "postal_code": "44195"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000012", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Acuity Medical Group — Multi-Specialty Clinic",
            "status": "A", "enumeration_date": "2018-03-11",
            "authorized_official_first_name": "Priya",
            "authorized_official_last_name": "Mehta",
            "authorized_official_title_or_position": "Practice Administrator",
            "authorized_official_telephone_number": "6175551200",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "55 Fruit St",
                        "city": "Boston", "state": "MA", "country_name": "US", "postal_code": "02114"}],
        "taxonomies": [{"code": "261QM1300X", "desc": "Clinic/Center Multi-Specialty", "primary": True}],
    },
    {
        "number": "1000000013", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Providence Health Technology Solutions",
            "status": "A", "enumeration_date": "2013-10-07",
            "authorized_official_first_name": "Mark",
            "authorized_official_last_name": "Ganz",
            "authorized_official_title_or_position": "CIO",
            "authorized_official_telephone_number": "5035551300",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "4400 NE Halsey St",
                        "city": "Portland", "state": "OR", "country_name": "US", "postal_code": "97213"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000014", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Inova Health Digital Transformation Office",
            "status": "A", "enumeration_date": "2017-04-15",
            "authorized_official_first_name": "Lisa",
            "authorized_official_last_name": "Bader",
            "authorized_official_title_or_position": "VP Clinical Informatics",
            "authorized_official_telephone_number": "7035551400",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "8110 Gatehouse Rd",
                        "city": "Falls Church", "state": "VA", "country_name": "US", "postal_code": "22042"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000015", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Atrium Health Innovation Hub",
            "status": "A", "enumeration_date": "2019-01-20",
            "authorized_official_first_name": "Eugene",
            "authorized_official_last_name": "Woods",
            "authorized_official_title_or_position": "Chief Executive Officer",
            "authorized_official_telephone_number": "7045551500",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "1000 Blythe Blvd",
                        "city": "Charlotte", "state": "NC", "country_name": "US", "postal_code": "28203"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000016", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "OhioHealth Rehabilitation Network",
            "status": "A", "enumeration_date": "2012-06-18",
            "authorized_official_first_name": "Karen",
            "authorized_official_last_name": "Morrison",
            "authorized_official_title_or_position": "Director of Operations",
            "authorized_official_telephone_number": "6145551600",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "180 E Broad St",
                        "city": "Columbus", "state": "OH", "country_name": "US", "postal_code": "43215"}],
        "taxonomies": [{"code": "261QR1300X", "desc": "Clinic/Center Rehabilitation", "primary": True}],
    },
    {
        "number": "1000000017", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Lifespan Health System EMR Initiative",
            "status": "A", "enumeration_date": "2011-09-03",
            "authorized_official_first_name": "William",
            "authorized_official_last_name": "Young",
            "authorized_official_title_or_position": "Chief Medical Informatics Officer",
            "authorized_official_telephone_number": "4015551700",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "167 Point St",
                        "city": "Providence", "state": "RI", "country_name": "US", "postal_code": "02903"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000018", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "Sutter Health Connected Care Platform",
            "status": "A", "enumeration_date": "2014-11-28",
            "authorized_official_first_name": "Nancy",
            "authorized_official_last_name": "Flores",
            "authorized_official_title_or_position": "SVP Technology & Innovation",
            "authorized_official_telephone_number": "9165551800",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "2200 River Plaza Dr",
                        "city": "Sacramento", "state": "CA", "country_name": "US", "postal_code": "95833"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000019", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "BJC HealthCare Digital Lab",
            "status": "A", "enumeration_date": "2016-03-08",
            "authorized_official_first_name": "Steven",
            "authorized_official_last_name": "Lipstein",
            "authorized_official_title_or_position": "President & CEO",
            "authorized_official_telephone_number": "3145551900",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "4901 Forest Park Ave",
                        "city": "St. Louis", "state": "MO", "country_name": "US", "postal_code": "63108"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
    {
        "number": "1000000020", "enumeration_type": "NPI-2",
        "basic": {
            "organization_name": "UnityPoint Health Telehealth Services",
            "status": "A", "enumeration_date": "2020-07-14",
            "authorized_official_first_name": "Susan",
            "authorized_official_last_name": "Evans",
            "authorized_official_title_or_position": "VP of Digital Health",
            "authorized_official_telephone_number": "5155552000",
        },
        "addresses": [{"address_purpose": "LOCATION", "address_1": "1776 W Lakes Pkwy",
                        "city": "West Des Moines", "state": "IA", "country_name": "US", "postal_code": "50266"}],
        "taxonomies": [{"code": "282N00000X", "desc": "General Acute Care Hospital", "primary": True}],
    },
]



class HealthcareDirectoryProvider(LeadDiscoveryProvider):
    """
    Free healthcare organization discovery using the CMS NPI Registry.

    Always enabled â€” no API key required.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._timeout = self._settings.provider_timeout_seconds
        self._npi_url = self._settings.npi_registry_url

    @property
    def name(self) -> ProviderName:
        return PROVIDER

    @property
    def is_enabled(self) -> bool:
        return True  # Always available â€” no key required

    async def search_companies(self, icp: ICPFilter) -> list[CandidateCompany]:
        """
        Search NPI registry for healthcare organizations matching ICP criteria.

        Runs one NPI query per relevant taxonomy category (concurrently,
        capped at MAX_TAXONOMY_QUERIES) and merges the results, deduping
        by NPI number. If the ICP gives explicit keywords, also runs a
        plain organization-name search, since that's a more specific
        signal than taxonomy category alone.

        Falls back to a curated demo dataset when the NPI API is unreachable
        (e.g. DNS failure, firewall) so that demos work offline.
        """
        taxonomy_queries = self._select_taxonomies(icp)
        num_queries = len(taxonomy_queries) + (1 if icp.keywords else 0)
        per_query_limit = max(5, min(50, icp.max_results // max(1, num_queries)))

        tasks = [
            self._search_by_taxonomy(icp, code, description, per_query_limit)
            for code, description in taxonomy_queries
        ]
        if icp.keywords:
            tasks.append(self._search_by_keyword(icp, per_query_limit))

        batches = await asyncio.gather(*tasks, return_exceptions=True)

        seen_npi: set[str] = set()
        results: list[CandidateCompany] = []
        failed_count = 0

        for batch in batches:
            if isinstance(batch, BaseException):
                logger.warning("NPI Registry: sub-query failed â€” %s", batch)
                failed_count += 1
                continue
            for company in batch:
                npi_number = (company.raw_payload or {}).get("number")
                if npi_number:
                    if npi_number in seen_npi:
                        continue
                    seen_npi.add(npi_number)
                results.append(company)

        # ── Fallback: use demo data when ALL queries failed (network unavailable) ──
        if failed_count == len(batches) and not results:
            logger.warning(
                "NPI Registry: ALL %d queries failed (DNS/network unavailable). "
                "Falling back to demo healthcare dataset for this run.",
                failed_count,
            )
            demo_data = {"results": _DEMO_NPI_RESULTS[: icp.max_results]}
            results = self._parse_npi_results(demo_data)
            logger.info(
                "NPI Registry [DEMO MODE]: returning %d pre-seeded healthcare organizations.",
                len(results),
            )
            return results

        results = results[: icp.max_results]
        logger.info(
            "NPI Registry: discovered %d healthcare organizations across %d taxonomy queries",
            len(results),
            len(taxonomy_queries),
        )
        return results

    def _select_taxonomies(self, icp: ICPFilter) -> list[tuple[str, str]]:
        """
        Pick which taxonomy categories to query this run.

        If the ICP's keywords/industries name a specific sub-type (e.g.
        "hospice", "nursing", "urgent care"), narrow to matching
        categories. Otherwise fall back to a broad, capped default set
        so a generic "healthcare" ICP still gets wide coverage without
        firing 20+ requests at the free NPI API in one run.
        """
        terms = " ".join((icp.keywords or []) + (icp.industries or [])).lower()
        if terms:
            matches = [
                (code, desc)
                for code, desc in HEALTHCARE_TAXONOMIES
                if any(word in desc.lower() for word in terms.split() if len(word) > 2)
            ]
            if matches:
                return matches[:MAX_TAXONOMY_QUERIES]

        return HEALTHCARE_TAXONOMIES[:MAX_TAXONOMY_QUERIES]

    async def _search_by_taxonomy(
        self, icp: ICPFilter, code: str, description: str, limit: int
    ) -> list[CandidateCompany]:
        params = self._build_npi_params(icp, limit)
        params["taxonomy_description"] = f"{description}*"
        try:
            data = await self._query_npi(params)
            return self._parse_npi_results(data)
        except ProviderTimeoutError:
            logger.warning(
                "NPI Registry: timed out on taxonomy '%s' (%s)", description, code
            )
            return []
        except ProviderResponseError as exc:
            logger.warning(
                "NPI Registry: response error on taxonomy '%s' â€” %s", description, exc
            )
            return []

    async def _search_by_keyword(
        self, icp: ICPFilter, limit: int
    ) -> list[CandidateCompany]:
        params = self._build_npi_params(icp, limit)
        params["organization_name"] = f"*{icp.keywords[0]}*"
        try:
            data = await self._query_npi(params)
            return self._parse_npi_results(data)
        except (ProviderTimeoutError, ProviderResponseError) as exc:
            logger.warning("NPI Registry: keyword search failed â€” %s", exc)
            return []

    async def search_contacts(
        self, company: CandidateCompany, target_roles: list[str]
    ) -> list[CandidateContact]:
        """
        NPI doesn't contain executives, but every organizational NPI
        registration (entity_type_code=2) has an "authorized official" â€”
        a real named individual (administrator, compliance officer,
        practice manager, etc.) who registered the org with CMS, along
        with their title and phone.

        This is stored on `company.raw_payload` (the original NPI record)
        but was previously discarded. Surfacing it here means NPI-sourced
        leads get a genuine name to start from instead of the generic
        "Unknown" placeholder the orchestrator falls back to when no
        provider returns a contact.

        Not a sales-qualified decision maker in most cases â€” but a real,
        reachable person is far more useful than nothing. Apollo remains
        the preferred source when available; this only fills the gap.
        """
        basic = (company.raw_payload or {}).get("basic") or {}

        first_name = basic.get("authorized_official_first_name")
        last_name = basic.get("authorized_official_last_name")

        if not first_name and not last_name:
            return []

        title = basic.get("authorized_official_title_or_position")
        phone = basic.get("authorized_official_telephone_number")
        credential = basic.get("authorized_official_credential")

        contact = CandidateContact(
            company_internal_id=company.internal_id,
            first_name=first_name,
            last_name=last_name,
            title=title,
            phone=phone,
            source_provider=PROVIDER,
            raw_payload={
                "authorized_official_credential": credential,
                "note": "Authorized official from NPI registration â€” "
                "not necessarily a sales decision maker.",
            },
        )
        return [contact]

    # â”€â”€â”€ NPI Query â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _build_npi_params(self, icp: ICPFilter, limit: int) -> dict[str, Any]:
        """Shared base params for any NPI sub-query. Callers add
        taxonomy_description or organization_name on top of this."""
        params: dict[str, Any] = {
            "version": "2.1",
            "entity_type_code": "2",  # 2 = Organization (not individual practitioners)
            "limit": min(limit, 50),
            "skip": 0,
        }

        # Add state filter from regions
        if icp.regions:
            state = _region_to_state(icp.regions[0])
            if state:
                params["state"] = state

        return params

    async def _query_npi(self, params: dict[str, Any]) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(self._npi_url, params=params)
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(PROVIDER.value, str(exc)) from exc
        except httpx.RequestError as exc:
            raise ProviderResponseError(PROVIDER.value, str(exc)) from exc

        if response.status_code != 200:
            raise ProviderResponseError(
                PROVIDER.value,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )

        try:
            return response.json()
        except Exception as exc:
            raise ProviderResponseError(
                PROVIDER.value, f"Invalid JSON: {exc}"
            ) from exc

    def _parse_npi_results(self, data: dict[str, Any]) -> list[CandidateCompany]:
        results_list = data.get("results") or []
        companies = []

        for result in results_list:
            basic = result.get("basic") or {}
            addresses = result.get("addresses") or []
            taxonomies = result.get("taxonomies") or []

            # Use mailing address as primary
            address = next(
                (a for a in addresses if a.get("address_purpose") == "LOCATION"),
                addresses[0] if addresses else {},
            )

            npi_number = result.get("number")
            name = (
                basic.get("organization_name")
                or basic.get("authorized_official_organization_name")
                or (f"Unnamed Healthcare Org (NPI {npi_number})" if npi_number else None)
            )
            if not name:
                # No usable identifier at all â€” skip rather than persist
                # a record nobody can act on or search for.
                continue

            # Get taxonomy description for industry classification
            taxonomy_desc = None
            if taxonomies:
                taxonomy_desc = taxonomies[0].get("desc")

            company = CandidateCompany(
                name=name,
                domain=None,  # NPI doesn't provide domains â€” enriched later
                website=None,
                industry=taxonomy_desc or "Healthcare",
                hq_city=address.get("city"),
                hq_state=address.get("state"),
                hq_country=address.get("country_name") or "US",
                description=f"NPI: {result.get('number')} | Type: {taxonomy_desc}",
                source_provider=PROVIDER,
                raw_payload=result,
            )
            companies.append(company)

        return companies


# â”€â”€â”€ Utility helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _region_to_state(region: str) -> str | None:
    """Map common region names to US state abbreviations."""
    mapping = {
        "california": "CA", "new york": "NY", "texas": "TX",
        "florida": "FL", "illinois": "IL", "pennsylvania": "PA",
        "ohio": "OH", "georgia": "GA", "michigan": "MI",
        "north carolina": "NC", "new jersey": "NJ", "virginia": "VA",
        "washington": "WA", "arizona": "AZ", "massachusetts": "MA",
        "tennessee": "TN", "indiana": "IN", "maryland": "MD",
        "missouri": "MO", "colorado": "CO", "minnesota": "MN",
        "us": None,  # National search â€” no state filter
        "united states": None,
    }
    return mapping.get(region.lower())
