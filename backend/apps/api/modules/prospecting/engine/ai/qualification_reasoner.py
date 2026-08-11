"""
ai/qualification_reasoner.py — LLM-powered lead qualification rationale.

After the rule-based ICP scorer produces a numeric score and breakdown,
this module asks the LLM to generate a human-readable rationale explaining:
  - Why this lead qualified (or was borderline).
  - What makes this company relevant to SETV's healthcare IT offering.
  - What angle a sales rep should lead with.

AI is used here because:
  - Generating a nuanced, rep-facing rationale from a score breakdown
    and company context requires language understanding.
  - A rule-based approach would produce mechanical, unhelpful text.

Returns None if LLM is unavailable — qualification still proceeds on
rule-based score alone.
"""

from __future__ import annotations

import logging

from apps.api.modules.prospecting.engine.ai.groq_client import GroqClient
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    CandidateContact,
    CompanyContext,
    ICPFilter,
)

logger = logging.getLogger(__name__)

# ─── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert healthcare B2B sales development representative (SDR) \
working for SETV Healthcare Technologies. Your company sells AI-powered \
healthcare IT solutions including digital transformation tools, EHR integrations, \
telehealth platforms, and clinical workflow automation.

Your job is to write a concise, actionable qualification note (2-4 sentences) \
that helps a sales rep understand:
1. Why this prospect is (or is not) a strong fit.
2. What specific signal or attribute makes them worth pursuing.
3. The best angle to lead with in outreach.

Be specific. Reference actual facts from the company data provided. \
Do not use generic filler phrases like "this company could benefit from...".
"""

_USER_PROMPT_TEMPLATE = """\
PROSPECT DETAILS:
Company: {company_name}
Industry: {industry}
Location: {location}
Estimated size: {size}
Company description: {description}
Tech focus: {tech_focus}
Digital transformation signals: {signals}

CONTACT:
Name: {contact_name}
Title: {contact_title}

ICP QUALIFICATION:
Score: {score}/100
Score breakdown: {breakdown}
{context_block}

Write a 2-4 sentence qualification rationale for this lead.
"""


class QualificationReasoner:
    """
    Generates natural language qualification rationale for leads.

    This is a pure AI enhancement layer — the qualification decision
    (qualified: bool, score: int) is already made by the rule-based
    LeadQualificationService before this is called.
    """

    def __init__(self, groq_client: GroqClient) -> None:
        self._groq = groq_client

    async def generate_rationale(
        self,
        company: CandidateCompany,
        contact: CandidateContact | None,
        icp: ICPFilter,
        score: int,
        breakdown: dict[str, int],
        company_context: CompanyContext | None,
    ) -> str | None:
        """
        Generate a qualification rationale for the given lead.

        Returns a string rationale, or None if LLM is unavailable.
        """
        prompt = self._build_prompt(
            company, contact, icp, score, breakdown, company_context
        )

        response = await self._groq.complete(
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=300,
            temperature=0.3,
        )

        if response is None:
            return None

        rationale = response.content.strip()

        # Sanity check — reject suspiciously short or empty outputs
        if len(rationale) < 20:
            logger.warning(
                "QualificationReasoner: LLM returned suspiciously short rationale "
                "for '%s': '%s'",
                company.name,
                rationale,
            )
            return None

        logger.debug(
            "Qualification rationale generated for '%s' (score=%d, model=%s)",
            company.name,
            score,
            response.model_used,
        )
        return rationale

    def _build_prompt(
        self,
        company: CandidateCompany,
        contact: CandidateContact | None,
        icp: ICPFilter,
        score: int,
        breakdown: dict[str, int],
        company_context: CompanyContext | None,
    ) -> str:
        location = ", ".join(
            filter(None, [company.hq_city, company.hq_state, company.hq_country])
        ) or "unknown"

        size = str(company.employee_count or company.employee_range or "unknown")

        breakdown_str = ", ".join(
            f"{k}: {v}/{_WEIGHTS.get(k, '?')}" for k, v in breakdown.items()
        )

        context_block = ""
        if company_context:
            if company_context.summary:
                context_block += f"\nResearch summary: {company_context.summary}"
            if company_context.digital_transformation_signals:
                sigs = ", ".join(company_context.digital_transformation_signals[:3])
                context_block += f"\nDigital transformation signals: {sigs}"

        return _USER_PROMPT_TEMPLATE.format(
            company_name=company.name,
            industry=company.industry or "unknown",
            location=location,
            size=size,
            description=(company.description or "")[:300],
            tech_focus=", ".join(
                (company_context.tech_focus[:5] if company_context else [])
            ) or "not available",
            signals=", ".join(
                (company_context.digital_transformation_signals[:3] if company_context else [])
            ) or "none detected",
            contact_name=contact.display_name if contact else "unknown",
            contact_title=contact.title if contact else "unknown",
            score=score,
            breakdown=breakdown_str,
            context_block=context_block,
        )


# Dimension max weights for display in prompt
_WEIGHTS = {"industry": 35, "size": 25, "region": 20, "role": 20}
