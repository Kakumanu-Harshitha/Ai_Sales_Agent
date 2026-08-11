"""
core/icp.py - ICP filter validation and scoring utilities.

The ICPFilter schema is defined in schemas/internal.py.
This module provides pure functions that operate on an ICPFilter to:
  - validate internal consistency
  - compute per-dimension scores against a company/contact/enriched-contact
  - produce a normalised 0-100 composite score

Weights (must sum to 100):
  INDUSTRY_WEIGHT        = 30
  SIZE_WEIGHT            = 20
  REGION_WEIGHT          = 15
  ROLE_WEIGHT            = 20
  ACTIONABILITY_WEIGHT   = 15

Hard gate (separate from score):
  qualified = (score >= threshold) AND (contact_actionability > 0)

All logic here is deterministic - no I/O, no AI.
"""

from __future__ import annotations

import re

from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    EnrichedContact,
    ICPFilter,
    VerificationStatus,
)


# --- Weight configuration ---------------------------------------------------
# Each dimension's maximum contribution to the total score (must sum to 100).

INDUSTRY_WEIGHT = 30
SIZE_WEIGHT = 20
REGION_WEIGHT = 15
ROLE_WEIGHT = 20
ACTIONABILITY_WEIGHT = 15

assert INDUSTRY_WEIGHT + SIZE_WEIGHT + REGION_WEIGHT + ROLE_WEIGHT + ACTIONABILITY_WEIGHT == 100


# --- Individual dimension scorers -------------------------------------------


def score_industry(company: CandidateCompany, icp: ICPFilter) -> int:
    """
    Returns INDUSTRY_WEIGHT if the company's industry matches any ICP industry,
    or 0 if no match. Returns INDUSTRY_WEIGHT/2 on partial keyword overlap.
    """
    if not icp.industries:
        # No constraint -> full marks (not penalised)
        return INDUSTRY_WEIGHT

    if not company.industry:
        return 0

    company_industry_lower = company.industry.lower()

    # Exact industry match
    for target in icp.industries:
        if target.lower() in company_industry_lower or company_industry_lower in target.lower():
            return INDUSTRY_WEIGHT

    # Partial keyword match (e.g. 'health' matches 'Healthcare IT')
    for target in icp.industries:
        words = [w.lower() for w in target.split()]
        if any(w in company_industry_lower for w in words if len(w) > 3):
            return INDUSTRY_WEIGHT // 2

    return 0


def score_size(company: CandidateCompany, icp: ICPFilter) -> int:
    """Returns SIZE_WEIGHT if employee count is within ICP range."""
    if icp.company_size_min is None and icp.company_size_max is None:
        return SIZE_WEIGHT  # No constraint

    count = _resolve_employee_count(company)
    if count is None:
        # Unknown size - give half credit rather than penalising
        return SIZE_WEIGHT // 2

    min_ok = icp.company_size_min is None or count >= icp.company_size_min
    max_ok = icp.company_size_max is None or count <= icp.company_size_max

    if min_ok and max_ok:
        return SIZE_WEIGHT

    # Slightly outside range - partial credit
    if icp.company_size_min and count < icp.company_size_min:
        ratio = count / icp.company_size_min
        if ratio >= 0.7:
            return SIZE_WEIGHT // 3

    if icp.company_size_max and count > icp.company_size_max:
        ratio = icp.company_size_max / count
        if ratio >= 0.7:
            return SIZE_WEIGHT // 3

    return 0


def score_region(company: CandidateCompany, icp: ICPFilter) -> int:
    """Returns REGION_WEIGHT if company geography overlaps ICP regions."""
    if not icp.regions:
        return REGION_WEIGHT

    company_geo = " ".join(
        filter(None, [company.hq_city, company.hq_state, company.hq_country])
    ).lower()

    if not company_geo:
        return REGION_WEIGHT // 2

    for region in icp.regions:
        if region.lower() in company_geo:
            return REGION_WEIGHT

    return 0


def score_role(contact: CandidateContact | None, icp: ICPFilter) -> int:
    """
    Returns ROLE_WEIGHT if the contact's title matches any ICP target role.
    If no contact or no target roles specified -> full marks.
    """
    if not icp.target_roles:
        return ROLE_WEIGHT

    if contact is None or not contact.title:
        return 0

    title_lower = contact.title.lower()

    for role in icp.target_roles:
        role_words = [w.lower() for w in role.split() if w.lower() not in {"of", "the", "and", "in", "for"}]
        if not role_words:
            continue

        if all(w in title_lower for w in role_words):
            return ROLE_WEIGHT
        # Partial match on any role word
        if any(w in title_lower for w in role_words):
            return ROLE_WEIGHT // 2

    return 0


def score_contact_actionability(enriched: EnrichedContact | None) -> int:
    """
    Returns ACTIONABILITY_WEIGHT (15) based on email availability and verification.

    This is also the HARD GATE dimension:
      - Score > 0 is required for full qualification.
      - A lead scoring >= threshold but with actionability == 0 is persisted
        as 'qualified_needs_contact_research', not 'new'.

    Scale:
      15 - verified email present
      10 - email present but unverified
       5 - no email but named contact with a title (reachable via manual research)
       0 - no contact at all (hard gate triggers)
    """
    if enriched is None:
        return 0

    contact = enriched.source_contact

    if enriched.email:
        if enriched.email_verification_status == VerificationStatus.VERIFIED:
            return ACTIONABILITY_WEIGHT          # 15
        return ACTIONABILITY_WEIGHT - 5          # 10

    # No email but we have a named, titled person
    if contact.title and (contact.first_name or contact.full_name):
        return ACTIONABILITY_WEIGHT // 3         # 5

    return 0


# --- Composite scorer -------------------------------------------------------


def compute_icp_score(
    company: CandidateCompany,
    contact: CandidateContact | None,
    icp: ICPFilter,
    enriched: EnrichedContact | None = None,
) -> tuple[int, dict[str, int]]:
    """
    Compute a composite ICP qualification score (0-100).

    Args:
        company: The company being evaluated.
        contact: Raw candidate contact (used for role scoring).
        icp: ICP filter criteria.
        enriched: Enriched contact (used for actionability scoring).
                  Pass None if enrichment has not yet run - actionability will be 0.

    Returns:
        (composite_score, breakdown_dict)

    The breakdown dict has keys: 'industry', 'size', 'region', 'role', 'contact_actionability'.
    """
    breakdown = {
        "industry": score_industry(company, icp),
        "size": score_size(company, icp),
        "region": score_region(company, icp),
        "role": score_role(contact, icp),
        "contact_actionability": score_contact_actionability(enriched),
    }
    total = sum(breakdown.values())
    return total, breakdown


def apply_hard_gate(
    score: int,
    breakdown: dict[str, int],
    threshold: int,
) -> tuple[bool, bool]:
    """
    Apply the two-condition qualification gate.

    Returns:
        (qualified, needs_contact_research)

    Logic:
      - qualified=True, needs_contact_research=False  -> full lead, ready to contact
      - qualified=False, needs_contact_research=True  -> passed score but no contact info
      - qualified=False, needs_contact_research=False -> failed score outright
    """
    passes_score = score >= threshold
    actionability = breakdown.get("contact_actionability", 0)

    if passes_score and actionability > 0:
        return True, False

    if passes_score and actionability == 0:
        # Cleared score threshold but zero contact actionability - soft-qualify
        return False, True

    return False, False


def build_disqualification_reasons(
    breakdown: dict[str, int],
    company: CandidateCompany,
    contact: CandidateContact | None,
    icp: ICPFilter,
) -> list[str]:
    """Return human-readable reasons why a lead fell below the threshold."""
    reasons = []

    if breakdown["industry"] == 0 and icp.industries:
        reasons.append(
            f"Industry '{company.industry}' does not match ICP targets: {icp.industries}"
        )

    if breakdown["size"] == 0:
        count = _resolve_employee_count(company)
        if count is not None:
            reasons.append(
                f"Company size {count} is outside ICP range "
                f"[{icp.company_size_min}, {icp.company_size_max}]"
            )
        else:
            reasons.append("Company size unknown and size is a hard ICP constraint")

    if breakdown["region"] == 0 and icp.regions:
        geo = " / ".join(filter(None, [company.hq_city, company.hq_state, company.hq_country]))
        reasons.append(f"Location '{geo or 'unknown'}' does not match ICP regions: {icp.regions}")

    if breakdown["role"] == 0 and icp.target_roles:
        title = contact.title if contact else "no contact"
        reasons.append(
            f"Contact role '{title}' does not match ICP target roles: {icp.target_roles}"
        )

    if breakdown.get("contact_actionability", 0) == 0:
        reasons.append(
            "No actionable contact found - no email or named decision maker with title"
        )

    return reasons


# --- Helpers ----------------------------------------------------------------

_RANGE_PATTERN = re.compile(r"(\d[\d,]*)\s*[-\u2013\u2014]\s*(\d[\d,]*)")


def _resolve_employee_count(company: CandidateCompany) -> int | None:
    """
    Return a concrete employee count from available fields.
    Falls back to parsing the employee_range string if employee_count is None.
    """
    if company.employee_count is not None:
        return company.employee_count

    if company.employee_range:
        m = _RANGE_PATTERN.search(company.employee_range)
        if m:
            low = int(m.group(1).replace(",", ""))
            high = int(m.group(2).replace(",", ""))
            return (low + high) // 2

    return None
