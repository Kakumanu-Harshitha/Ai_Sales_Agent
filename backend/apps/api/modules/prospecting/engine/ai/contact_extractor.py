"""
ai/contact_extractor.py - Groq-powered named contact extraction.

Given raw web page text from leadership, about, team, or contact pages,
uses the Groq LLM to extract structured named decision makers and their titles,
as well as all available signals: literal emails, phones, departments, locations,
organization type, and leadership page indicators.

This is the P1 provider-independent discovery path:
  Tavily fetches page content -> ContactExtractor pulls names/titles/emails -> CandidateContacts

Returns empty list (never raises) when Groq is unavailable.
"""

from __future__ import annotations

import json
import logging
import re

from apps.api.modules.prospecting.engine.ai.groq_client import GroqClient

logger = logging.getLogger(__name__)

# --- Prompts ----------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a B2B sales research assistant. Your task is to extract all available \
information about executives, decision makers, and senior leaders from company \
web page text. Return ONLY valid JSON and nothing else. \
Extract every available signal -- do not discard anything useful.
"""

_USER_PROMPT_TEMPLATE = """\
Company Name: {company_name}
Source URL: {url}

--- Page Content ---
{page_text}
--- End of Content ---

Extract all named executives, directors, VPs, C-suite, and healthcare \
decision makers mentioned in the text above. For each person, extract as many \
fields as are available in the text. Return a JSON object with exactly this structure:

{{
  "organization_type": "hospital | clinic | imaging center | laboratory | home health | rehab | practice | other | null",
  "is_leadership_page": true,
  "contacts": [
    {{
      "name": "Full Name",
      "title": "Job Title or null if unknown",
      "department": "Department or null",
      "email": "literal@email.com or null",
      "phone": "phone number or null",
      "location": "City, State or null",
      "confidence": 0.0
    }}
  ]
}}

Rules:
- organization_type: Classify from context. Use: hospital, clinic, imaging center, laboratory, home health, rehab, practice, or other.
- is_leadership_page: true if this is a leadership, board, executive, administration, or provider directory page.
- Only include NAMED individuals (not generic roles like "our team").
- email: ONLY include if a literal email address appears in the text. Do NOT guess or fabricate emails.
- phone: Only include if a literal phone number appears in the text.
- Confidence: 0.9 = name + title explicitly on a leadership page, 0.7 = name + implied role, 0.5 = name only.
- Return an empty contacts list if no individuals are found.
- Do not hallucinate. Maximum 10 contacts.
"""


class ContactExtractor:
    """
    Extracts named decision makers and all available page signals from
    unstructured company web page text using Groq.

    Stateless - instantiate once and call extract() per company.
    Returns ([], {}) when Groq is unavailable or extraction fails.
    """

    def __init__(self, groq_client: GroqClient) -> None:
        self._groq = groq_client

    async def extract(
        self,
        page_text: str,
        company_name: str,
        source_url: str | None = None,
    ) -> tuple[list[dict], dict]:
        """
        Extract contact candidates and page-level metadata from page text.

        Args:
            page_text: Raw visible text from one or more company web pages.
            company_name: Used in the prompt for context.
            source_url: Displayed in prompt; also logged for audit.

        Returns:
            Tuple of:
              - List of contact dicts with keys: name, title, department, email,
                phone, location, confidence.
              - Page metadata dict with keys: organization_type, is_leadership_page.
            Returns ([], {}) on failure or when Groq is unavailable.
        """
        if not page_text or len(page_text.strip()) < 50:
            logger.debug(
                "ContactExtractor: page text too short for '%s'", company_name
            )
            return [], {}

        truncated = page_text[:6000]  # Stay within token limit
        prompt = _USER_PROMPT_TEMPLATE.format(
            company_name=company_name,
            url=source_url or "unknown",
            page_text=truncated,
        )

        response = await self._groq.complete(
            system=_SYSTEM_PROMPT,
            prompt=prompt,
            max_tokens=3000,
            temperature=0.0,
        )

        if response is None:
            logger.debug(
                "ContactExtractor: Groq unavailable for '%s'", company_name
            )
            return [], {}

        return self._parse(response.content, company_name)

    def _parse(self, raw: str, company_name: str) -> tuple[list[dict], dict]:
        """Parse LLM JSON response into a list of contact dicts and page metadata."""
        clean = re.sub(r"```(?:json)?|```", "", raw).strip()

        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            logger.warning(
                "ContactExtractor: invalid JSON from LLM for '%s'. Raw: %.200s",
                company_name, raw,
            )
            return [], {}

        # Fallback if LLM returns a raw list instead of an object
        if isinstance(data, list):
            data = {"contacts": data}

        # Page-level metadata
        page_meta = {
            "organization_type": data.get("organization_type"),
            "is_leadership_page": bool(data.get("is_leadership_page", False)),
        }

        contacts_raw = data.get("contacts") or []
        results = []
        for item in contacts_raw:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()
            title = (item.get("title") or "").strip() or None
            department = (item.get("department") or "").strip() or None
            email = (item.get("email") or "").strip() or None
            phone = (item.get("phone") or "").strip() or None
            location = (item.get("location") or "").strip() or None
            confidence = float(item.get("confidence", 0.5))

            # Basic email sanity - must contain @ and a dot after it
            if email and ("@" not in email or "." not in email.split("@")[-1]):
                email = None

            if name and len(name) > 2 and confidence >= 0.5:
                results.append({
                    "name": name,
                    "title": title,
                    "department": department,
                    "email": email,
                    "phone": phone,
                    "location": location,
                    "confidence": confidence,
                })

        logger.debug(
            "ContactExtractor: extracted %d contact(s) from '%s' "
            "(org_type=%s, leadership_page=%s)",
            len(results), company_name,
            page_meta.get("organization_type"),
            page_meta.get("is_leadership_page"),
        )
        return results, page_meta
