"""
services/qualification.py â€” LeadQualificationService.

Responsibility: Decide whether a company + contact pair qualifies as a
lead worth persisting, and compute a qualification score.

Two-phase approach:
  1. Rule-based ICP scoring (deterministic, always runs).
     Uses core/icp.py scoring functions.
     Produces a numeric score (0-100) and per-dimension breakdown.

  2. LLM qualification reasoning (optional, runs if Groq is available).
     Generates a human-readable rationale for the sales rep.
     If LLM is unavailable, the qualification decision still stands â€”
     only the rationale is missing.

A lead qualifies if its score >= qualification_threshold (from config).
"""

from __future__ import annotations

import logging

from apps.api.modules.prospecting.engine.ai.groq_client import GroqClient
from apps.api.modules.prospecting.engine.ai.qualification_reasoner import QualificationReasoner
from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.icp import build_disqualification_reasons, compute_icp_score
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    EnrichedContact,
    CompanyContext,
    ICPFilter,
    QualificationResult,
)

logger = logging.getLogger(__name__)


class LeadQualificationService:
    """
    Qualifies company + contact pairs against ICP criteria.

    The service is designed to be stateless â€” instantiate once and call
    qualify() for each company/contact combination.
    """

    def __init__(self, groq_client: GroqClient) -> None:
        self._groq = groq_client
        self._reasoner = QualificationReasoner(groq_client)
        self._threshold = get_settings().qualification_threshold

    async def qualify(
        self,
        company: CandidateCompany,
        contact: CandidateContact | None,
        icp: ICPFilter,
        company_context: CompanyContext | None = None,
        enriched: EnrichedContact | None = None,
    ) -> QualificationResult:
        """
        Qualify a company + contact pair against ICP criteria.

        Args:
            company: The company under evaluation.
            contact: The primary contact (decision maker). May be None if
                     no contacts were found â€” company is still scored.
            icp: ICP filter criteria.
            company_context: Optional LLM-synthesized company context,
                             used to enrich the LLM rationale.

        Returns:
            QualificationResult with score, breakdown, qualified flag,
            and optional rationale.
        """
        # â”€â”€ Phase 1: Rule-based scoring â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        score, breakdown = compute_icp_score(company, contact, icp, enriched=enriched)
        qualified = score >= self._threshold

        logger.debug(
            "Qualification: '%s' scored %d/%d (threshold=%d) â†’ %s",
            company.name, score, 100, self._threshold,
            "QUALIFIED" if qualified else "DISQUALIFIED",
        )

        disqualification_reasons: list[str] = []
        if not qualified:
            disqualification_reasons = build_disqualification_reasons(
                breakdown, company, contact, icp
            )

        # â”€â”€ Phase 2: LLM rationale (optional enhancement) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        rationale: str | None = None

        # Only generate rationale for leads that qualify or are borderline
        # (within 15 points of threshold). Skip for clearly disqualified leads.
        should_reason = qualified or (score >= self._threshold - 15)

        if should_reason:
            try:
                rationale = await self._reasoner.generate_rationale(
                    company=company,
                    contact=contact,
                    icp=icp,
                    score=score,
                    breakdown=breakdown,
                    company_context=company_context,
                )
            except Exception as exc:
                # LLM failure is non-fatal â€” log and continue
                logger.warning(
                    "LLM qualification reasoning failed for '%s': %s",
                    company.name, exc,
                )

        return QualificationResult(
            qualified=qualified,
            score=score,
            score_breakdown=breakdown,
            rationale=rationale,
            disqualification_reasons=disqualification_reasons,
        )

    def update_threshold(self, threshold: int) -> None:
        """Allow runtime threshold adjustment (e.g., for testing)."""
        self._threshold = max(0, min(100, threshold))

