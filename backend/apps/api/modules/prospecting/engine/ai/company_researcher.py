"""
ai/company_researcher.py — LLM-powered company context extraction.

Given unstructured text from a company's public website, this module
uses the Groq LLM to extract structured context: summary, tech stack,
digital transformation signals, and key decision makers mentioned.

AI is used here because:
  - The input is unstructured HTML/text that cannot be reliably parsed by regex.
  - We need semantic understanding (e.g. 'we're going paperless' → digital transformation).
  - The extraction problem varies significantly across company pages.

The module returns a CompanyContext (or None on failure) — callers must
handle None gracefully.
"""

from __future__ import annotations

import json
import logging
import re

from apps.api.modules.prospecting.engine.ai.groq_client import GroqClient
from apps.api.modules.prospecting.engine.schemas.internal import CompanyContext

logger = logging.getLogger(__name__)

# ─── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert healthcare B2B sales researcher. Your task is to extract \
structured information from a company's public web page text to help a sales \
team understand if this company is a good prospect for healthcare IT and \
digital transformation solutions.

Always respond with valid JSON only. Do not include any explanation, \
markdown code fences, or extra text — just raw JSON.
"""

_USER_PROMPT_TEMPLATE = """\
Company Name: {company_name}
Website URL: {url}

--- Page Content ---
{page_text}
--- End of Content ---

Extract the following information from the page content above and return \
as a JSON object with exactly these keys:

{{
  "summary": "1-2 sentence description of what this company does",
  "tech_focus": ["list", "of", "technologies", "or", "platforms", "mentioned"],
  "digital_transformation_signals": [
    "any signal that this company is investing in or interested in digital transformation, \
EHR, telehealth, AI in healthcare, going paperless, etc."
  ],
  "decision_makers_mentioned": ["full names of executives or leaders mentioned on the page"],
  "estimated_size": "small/mid-size/large/enterprise or null if not determinable",
  "key_products_services": ["list", "of", "their", "main", "products", "or", "services"]
}}

If a field has no information, use an empty list [] or null. \
Do not guess or hallucinate facts not present in the page content.
"""


class CompanyResearcher:
    """
    Extracts structured context from unstructured company web page text.

    The researcher is intentionally stateless — instantiate once and call
    research() for each company.
    """

    def __init__(self, groq_client: GroqClient) -> None:
        self._groq = groq_client

    async def research(
        self,
        company_name: str,
        page_text: str,
        source_url: str | None = None,
    ) -> CompanyContext | None:
        """
        Parse unstructured company page text into a CompanyContext.

        Returns None if LLM is unavailable or extraction fails.
        This is always a best-effort operation — callers proceed without it.
        """
        if not page_text or len(page_text.strip()) < 50:
            logger.debug("Company '%s': page text too short for research", company_name)
            return None

        # Truncate to stay within token limits
        truncated_text = page_text[:4000]

        prompt = _USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            url=source_url or "unknown",
            page_text=truncated_text,
        )

        response = await self._groq.complete(
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=800,
            temperature=0.1,
        )

        if response is None:
            return None

        return self._parse_response(response.content, source_url, response.model_used)

    def _parse_response(
        self,
        raw: str,
        source_url: str | None,
        model: str,
    ) -> CompanyContext | None:
        """Parse and validate the LLM JSON response into a CompanyContext."""
        # Strip any accidental markdown code fences
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()

        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning(
                "CompanyResearcher: LLM returned invalid JSON. Raw: %.200s", raw
            )
            # Attempt partial extraction from malformed output
            return self._partial_extract(raw, source_url, model)

        return CompanyContext(
            summary=data.get("summary"),
            tech_focus=_to_str_list(data.get("tech_focus")),
            digital_transformation_signals=_to_str_list(
                data.get("digital_transformation_signals")
            ),
            decision_makers_mentioned=_to_str_list(
                data.get("decision_makers_mentioned")
            ),
            estimated_size=data.get("estimated_size"),
            key_products_services=_to_str_list(data.get("key_products_services")),
            research_source_url=source_url,
            llm_model_used=model,
        )

    def _partial_extract(
        self, raw: str, source_url: str | None, model: str
    ) -> CompanyContext | None:
        """Best-effort extraction when JSON parsing fails — return minimal context."""
        # Try to at least salvage the summary if it's a plain-text response
        if len(raw) > 20:
            return CompanyContext(
                summary=raw[:300],
                research_source_url=source_url,
                llm_model_used=model,
            )
        return None


def _to_str_list(value: object) -> list[str]:
    """Safely convert a JSON value to a list of strings."""
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []
