"""
services/deduplication.py â€” DeduplicationService.

Responsibility: Prevent duplicate companies and contacts from being
created in the database. Deduplication happens at two levels:

1. In-memory deduplication (within a single search run):
   - Multiple providers may return the same company.
   - Domain-based exact match catches obvious duplicates.
   - Fuzzy name match catches spelling variations.

2. Database deduplication (against existing records):
   - Check if a company/contact already exists in the DB before insert.
   - If found â†’ merge new data into the existing record.

All logic is deterministic â€” no AI, no external calls.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

from rapidfuzz import fuzz

from apps.api.modules.prospecting.engine.schemas.internal import CandidateCompany, CandidateContact

logger = logging.getLogger(__name__)

# Minimum fuzzy name similarity to consider two companies the same (0-100)
FUZZY_NAME_THRESHOLD = 85

# Characters to strip when normalizing company names for comparison
_NORMALISE_RE = re.compile(r"[^\w\s]")
_SUFFIXES_RE = re.compile(
    r"\b(?:inc|llc|ltd|corp|corporation|group|holdings|health|"
    r"healthcare|system|systems|hospital|hospitals|clinic|clinics|"
    r"medical|center|centres?|associates?|services?)\b",
    re.IGNORECASE,
)


class DeduplicationService:
    """
    Removes duplicate CandidateCompany and CandidateContact objects.

    Usage:
        service = DeduplicationService()

        # Deduplicate within a discovery run
        unique_companies = service.deduplicate_companies(raw_companies)

        # Check if a domain already exists in the DB
        existing = await repository.find_duplicate_company(domain, name)
        if existing:
            # Merge / skip
    """

    def deduplicate_companies(
        self, companies: list[CandidateCompany]
    ) -> list[CandidateCompany]:
        """
        Remove duplicate companies from a list using domain + fuzzy name matching.

        Rules (in priority order):
          1. Same domain â†’ definite duplicate; keep whichever came first.
          2. Fuzzy name similarity >= threshold with no domain on either â†’ probable duplicate.

        Returns a deduplicated list preserving insertion order (first seen wins).
        """
        seen_domains: dict[str, CandidateCompany] = {}
        unique: list[CandidateCompany] = []

        for company in companies:
            # â”€â”€ Domain match â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            domain = _normalise_domain(company.domain)
            if domain and domain in seen_domains:
                logger.debug(
                    "Dedup: skipping '%s' â€” domain '%s' already seen (from '%s')",
                    company.name, domain, seen_domains[domain].name,
                )
                continue

            # â”€â”€ Fuzzy name match against already-accepted companies â”€â”€â”€â”€â”€â”€â”€â”€
            if self._fuzzy_duplicate(company, unique):
                logger.debug(
                    "Dedup: skipping '%s' â€” fuzzy name match found in current run",
                    company.name,
                )
                continue

            # â”€â”€ Accept â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
            if domain:
                seen_domains[domain] = company
            unique.append(company)

        removed = len(companies) - len(unique)
        if removed:
            logger.info(
                "Deduplication: removed %d duplicate companies (kept %d of %d)",
                removed, len(unique), len(companies),
            )
        return unique

    def deduplicate_contacts(
        self, contacts: list[CandidateContact]
    ) -> list[CandidateContact]:
        """
        Remove duplicate contacts within a list.

        Duplicate detection:
          1. Same email address (case-insensitive)
          2. Same full name + company_internal_id combination
        """
        seen_emails: set[str] = set()
        seen_name_company: set[tuple[str, str]] = set()
        unique: list[CandidateContact] = []

        for contact in contacts:
            # Email dedup
            if contact.email:
                email_key = contact.email.lower().strip()
                if email_key in seen_emails:
                    continue
                seen_emails.add(email_key)

            # Name + company dedup
            name = (contact.display_name or "").lower().strip()
            if name and name != "unknown":
                key = (name, contact.company_internal_id)
                if key in seen_name_company:
                    continue
                seen_name_company.add(key)

            unique.append(contact)

        return unique

    def is_duplicate_company(
        self,
        candidate: CandidateCompany,
        existing_domain: str | None,
        existing_name: str | None,
    ) -> bool:
        """
        Check if a candidate company matches an existing DB record.

        Used by ProspectRepository after a DB lookup to decide merge vs. insert.
        """
        # Domain match
        if candidate.domain and existing_domain:
            if _normalise_domain(candidate.domain) == _normalise_domain(existing_domain):
                return True

        # Name match
        if candidate.name and existing_name:
            score = fuzz.token_sort_ratio(
                _normalise_name(candidate.name),
                _normalise_name(existing_name),
            )
            if score >= FUZZY_NAME_THRESHOLD:
                return True

        return False

    # â”€â”€â”€ Private helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _fuzzy_duplicate(
        self,
        candidate: CandidateCompany,
        accepted: list[CandidateCompany],
    ) -> bool:
        """Return True if the candidate is fuzzy-similar to any accepted company."""
        norm_candidate = _normalise_name(candidate.name)
        for accepted_company in accepted:
            norm_accepted = _normalise_name(accepted_company.name)
            score = fuzz.token_sort_ratio(norm_candidate, norm_accepted)
            if score >= FUZZY_NAME_THRESHOLD:
                return True
        return False


# â”€â”€â”€ Normalisation helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


def _normalise_domain(domain: str | None) -> str | None:
    """Normalise a domain to lowercase, strip www. prefix."""
    if not domain:
        return None
    return domain.lower().strip().removeprefix("www.").rstrip("/")


def _normalise_name(name: str) -> str:
    """
    Normalise a company name for fuzzy comparison:
      - Lowercase
      - Remove punctuation
      - Remove common corporate suffixes that obscure the actual name
    """
    name = name.lower()
    name = _NORMALISE_RE.sub(" ", name)
    name = _SUFFIXES_RE.sub(" ", name)
    name = " ".join(name.split())  # Collapse whitespace
    return name

