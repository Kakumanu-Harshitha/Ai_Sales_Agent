"""
services/contact_pool.py - ContactCandidatePool.

Collects every contact candidate from every provider during a single
company pipeline run, ranks them, and returns the single best candidate
for email enrichment (Lane B).

Ranking criteria (weighted composite, higher = better):
  - Seniority:              CxO=100, VP/Director=80, Manager=60, Admin=30, unknown=0
  - Role relevance:         Title overlap with ICP target_roles (0-100)
  - Source reliability:     Provider default (adjustable, see CandidateContact.source_reliability)
  - Literal email present:  +20 bonus if extracted_email is populated
  - Leadership page:        +15 bonus if leadership_indicator is True
  - Cross-source corroboration: +10 if same person found by multiple sources
  - Extraction confidence:  Modifies role/seniority score proportionally
  - Email available:        +8 bonus if any email (contact.email) is already populated

Only the best-ranked candidate is passed to the email resolver.
The selection_reason field is populated on the winner for explainability.
"""

from __future__ import annotations

import logging
import re

from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateContact,
    ContactScore,
    ICPFilter,
)

logger = logging.getLogger(__name__)

# --- Seniority keyword maps (descending priority) ----------------------------

_SENIORITY_TIERS: list[tuple[int, list[str]]] = [
    (100, ["chief executive", "ceo", "chief operating", "coo", "chief technology", "cto",
           "chief information", "cio", "chief medical", "cmo", "chief digital", "cdo",
           "chief financial", "cfo", "chief nursing", "cno", "president", "founder",
           "co-founder", "owner", "managing director", "general manager"]),
    (80,  ["vice president", "vp of", "vp,", "vp ", "director", "head of", "head,",
           "senior director", "executive director", "associate vp", "medical director",
           "clinical director", "laboratory director"]),
    (60,  ["manager", "supervisor", "lead ", "team lead", "senior manager",
           "it manager", "health informatics", "informatics manager",
           "operations manager", "administrator", "practice manager"]),
    (30,  ["coordinator", "specialist", "analyst", "associate", "consultant",
           "officer", "representative", "contact"]),
]


def _seniority_score(title: str | None) -> int:
    """Return a seniority score (0-100) based on title keywords."""
    if not title:
        return 0
    title_lower = title.lower()
    for score, keywords in _SENIORITY_TIERS:
        if any(kw in title_lower for kw in keywords):
            return score
    return 0


def _role_relevance_score(title: str | None, target_roles: list[str]) -> int:
    """
    Return 0-100 based on how well the contact title overlaps with ICP target_roles.
    Full match = 100, partial match = 50, no match or no roles specified = 50 (neutral).
    """
    if not target_roles:
        return 50  # No constraint -> neutral score

    if not title:
        return 0

    title_lower = title.lower()

    for role in target_roles:
        role_words = [
            w.lower() for w in role.split()
            if w.lower() not in {"of", "the", "and", "in", "for"}
        ]
        if not role_words:
            continue
        if all(w in title_lower for w in role_words):
            return 100
        if any(w in title_lower for w in role_words):
            return 50

    return 0


def _normalize_name(name: str | None) -> str:
    """Normalize a person's name for fuzzy cross-source deduplication."""
    if not name:
        return ""
    return re.sub(r"\s+", "", name.lower().strip())


class ContactCandidatePool:
    """
    Multi-provider contact candidate pool with advanced ranking.

    Ranking rewards:
      - Seniority and role relevance (primary signals)
      - Literal email extracted from page content (strong +20 bonus)
      - Found on a leadership/board/executive page (+15 bonus)
      - Corroborated by multiple independent sources (+10 bonus)
      - Higher extraction confidence (multiplier on role/seniority)
      - Email already populated from any source (+8 bonus)

    Usage:
        pool = ContactCandidatePool(icp)
        pool.add_all(contacts_from_apollo)
        pool.add_all(contacts_from_tavily)
        pool.add_all(contacts_from_npi)
        best = pool.select_best()   # returns CandidateContact | None
    """

    def __init__(self, icp: ICPFilter) -> None:
        self._icp = icp
        self._candidates: list[tuple[CandidateContact, ContactScore]] = []
        # Track normalized names -> set of source provider values that found them
        self._name_sources: dict[str, set[str]] = {}

    def add(self, contact: CandidateContact) -> None:
        """Score and add a single contact to the pool."""
        # Track distinct providers that found this person (for corroboration)
        norm_name = _normalize_name(contact.display_name)
        if norm_name:
            self._name_sources.setdefault(norm_name, set()).add(contact.source_provider.value)

        score = self._score(contact)
        self._candidates.append((contact, score))
        logger.debug(
            "Pool: added '%s' (%s) source=%s composite=%d",
            contact.display_name, contact.title or "no title",
            contact.source_provider.value, score.composite,
        )

    def add_all(self, contacts: list[CandidateContact]) -> None:
        """Score and add multiple contacts."""
        for c in contacts:
            self.add(c)

    def select_best(self) -> CandidateContact | None:
        """
        Return the highest-ranked candidate with selection_reason populated,
        or None if the pool is empty.

        A two-pass approach: first collect all candidates, then re-score with
        final corroboration counts before selecting the winner.
        Ties are broken by insertion order (first provider wins).
        """
        if not self._candidates:
            logger.debug("ContactCandidatePool: empty - no contacts discovered")
            return None

        # Re-score with finalized corroboration counts
        rescored = [
            (contact, self._score(contact, finalize=True))
            for contact, _ in self._candidates
        ]

        best_contact, best_score = max(rescored, key=lambda pair: pair[1].composite)

        # Build human-readable selection reason for explainability
        reason_parts = []
        if best_score.seniority >= 80:
            reason_parts.append(f"high seniority ({best_contact.title})")
        elif best_score.seniority >= 60:
            reason_parts.append(f"mid-level role ({best_contact.title})")
        if best_score.role_relevance >= 100:
            reason_parts.append("exact ICP role match")
        elif best_score.role_relevance >= 50:
            reason_parts.append("partial ICP role match")
        if best_contact.extracted_email:
            reason_parts.append(f"literal email found: {best_contact.extracted_email}")
        if best_contact.leadership_indicator:
            reason_parts.append("found on leadership/board page")
        norm_name = _normalize_name(best_contact.display_name)
        source_count = len(self._name_sources.get(norm_name, set()))
        if source_count > 1:
            reason_parts.append(f"corroborated by {source_count} independent sources")
        source_ref = best_contact.source_url or best_contact.source_provider.value
        reason_parts.append(f"source: {source_ref}")
        selection_reason = "; ".join(reason_parts) if reason_parts else "highest composite score"

        # Attach selection_reason to the winning contact
        best_contact = best_contact.model_copy(update={"selection_reason": selection_reason})

        logger.info(
            "ContactCandidatePool: selected '%s' (%s) source=%s composite=%d "
            "[seniority=%d role_rel=%d src_rel=%d email_bonus=%d leadership=%d corroboration=%d]\n"
            "  Reason: %s",
            best_contact.display_name,
            best_contact.title or "no title",
            best_contact.source_provider.value,
            best_score.composite,
            best_score.seniority,
            best_score.role_relevance,
            best_score.source_reliability,
            best_score.email_available,
            best_score.email_verified,
            source_count,
            selection_reason,
        )
        return best_contact

    def all_ranked(self) -> list[CandidateContact]:
        """Return all candidates sorted best-first (for debugging/audit)."""
        rescored = [
            (contact, self._score(contact, finalize=True))
            for contact, _ in self._candidates
        ]
        return [
            c for c, _ in sorted(rescored, key=lambda pair: pair[1].composite, reverse=True)
        ]

    @property
    def size(self) -> int:
        return len(self._candidates)

    # --- Internal -----------------------------------------------------------

    def _score(self, contact: CandidateContact, finalize: bool = False) -> ContactScore:
        """Compute composite ranking score for a single contact."""
        seniority = _seniority_score(contact.title)
        role_rel = _role_relevance_score(contact.title, self._icp.target_roles)
        src_rel = contact.source_reliability

        # Literal email extracted from page: strongest bonus (max 20)
        extracted_email_bonus = 20 if contact.extracted_email else 0

        # Leadership/board page indicator: strong bonus (max 15)
        leadership_bonus = 15 if contact.leadership_indicator else 0

        # Cross-source corroboration: only computed in finalize pass (max 10)
        corroboration_bonus = 0
        if finalize:
            norm_name = _normalize_name(contact.display_name)
            source_count = len(self._name_sources.get(norm_name, set()))
            if source_count > 1:
                corroboration_bonus = min(10, (source_count - 1) * 5)

        # Email available from any source: small bonus (max 8)
        email_avail = 8 if contact.email else 0

        # Extraction confidence scales the role+seniority portion (0.5->0.70x, 1.0->1.00x)
        conf = max(0.5, min(1.0, contact.extraction_confidence))
        conf_multiplier = 0.7 + (conf - 0.5) * 0.6

        # Weighted composite with confidence scaling on role/seniority only
        raw_scaled = (
            (seniority * 0.35 + role_rel * 0.25) * conf_multiplier
            + src_rel * 0.20
            + extracted_email_bonus
            + leadership_bonus
            + corroboration_bonus
            + email_avail
        )

        composite = min(100, int(raw_scaled))

        # email_available repurposed to hold total email bonuses; email_verified for leadership
        return ContactScore(
            seniority=seniority,
            role_relevance=role_rel,
            source_reliability=src_rel,
            email_available=extracted_email_bonus + email_avail,
            email_verified=leadership_bonus,
            composite=composite,
        )
