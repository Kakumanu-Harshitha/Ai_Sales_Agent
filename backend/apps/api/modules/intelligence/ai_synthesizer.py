"""
AI Synthesizer — Company Intelligence Engine.

Takes all collected raw intelligence (website text, LinkedIn activity,
news events) and passes it to the AI Provider to generate a structured
Company Intelligence Summary.

The synthesizer is optimised to:
  - Compress raw content to fit within LLM context limits
  - Use structured JSON output for reliable parsing
  - Generate actionable sales intelligence, not generic summaries
"""

import json
import logging
from typing import Any

from apps.api.core.ai_provider import AIProvider

logger = logging.getLogger(__name__)

AI_SYNTHESIS_SYSTEM = """You are an expert B2B Sales Intelligence Analyst specialising in healthcare technology companies.

Your job is to analyse all available public intelligence about a company and produce a structured Company Intelligence Summary that will be used by sales teams and AI agents for personalised outreach, buying signal detection, and deal qualification.

CRITICAL RULES:
- Only use information that is provided in the context. Do NOT invent facts.
- If information is not available for a field, leave it as null or empty list.
- Focus on actionable insights useful for a B2B sales team.
- Prioritise healthcare, AI, and digital transformation signals.

Return a JSON object with the following structure (fill all available fields):

{
  "company_overview": "2-3 sentence overview of the company",
  "business_model": "Brief description of how the company makes money (SaaS, services, products, etc.)",
  "industry": "Primary industry (e.g. Healthcare IT, Clinical Software, Health Systems)",
  "core_products_services": ["product 1", "product 2"],
  "current_priorities": "What the company seems to be focused on right now",
  "business_goals": "Inferred long-term goals based on public signals",
  "technology_focus": "Key technologies they are investing in or using",
  "healthcare_focus": "Specific healthcare areas they serve (clinical, administrative, diagnostic, etc.)",
  "ai_initiatives": "Any AI or ML-related initiatives, products, or investments",
  "digital_transformation": "Digital transformation efforts or announcements",
  "innovation_areas": ["area 1", "area 2"],
  "recent_initiatives": "Recent strategic moves (partnerships, launches, expansions)",
  "expansion_plans": "Any expansion plans (geographical, product, vertical)",
  "global_presence": "Countries or regions they operate in",
  "research_programs": "Any research, clinical trials, or academic partnerships",
  "hiring_activity": "Current hiring trends (what roles, which departments)",
  "potential_challenges": "Likely business challenges they face right now",
  "possible_opportunities": "Business opportunities where SETV could provide value",
  "buying_signals_detected": ["signal 1", "signal 2"],
  "intelligence_completeness": 85
}

The intelligence_completeness field should be a number 0-100 indicating how complete this profile is based on available data.
"""


class AISynthesizer:
    """
    Calls the AI Provider with all collected intelligence and
    returns a structured summary dict.
    """

    def synthesize(
        self,
        company_name: str,
        website_texts: list[dict[str, Any]],
        linkedin_activities: list[dict[str, Any]],
        news_events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """
        Synthesize all intelligence into a structured Company Intelligence Summary.

        Args:
            company_name: Name of the company
            website_texts: List of {page_type, text} dicts from website scraper
            linkedin_activities: List of activity summary dicts
            news_events: List of news event dicts

        Returns:
            Structured dict or None if AI call fails
        """
        prompt = self._build_prompt(company_name, website_texts, linkedin_activities, news_events)

        try:
            result = AIProvider().generate_content(
                system_instruction=AI_SYNTHESIS_SYSTEM,
                prompt=prompt,
            )
            if result and isinstance(result, dict):
                # Strip wrapper key if present
                if "data" in result and isinstance(result["data"], dict):
                    return result["data"]
                return result
        except Exception as exc:
            logger.error("AI synthesis failed for '%s': %s", company_name, exc)

        return None

    def _build_prompt(
        self,
        company_name: str,
        website_texts: list[dict],
        linkedin_activities: list[dict],
        news_events: list[dict],
    ) -> str:
        """Build the synthesis prompt from raw intelligence data."""
        sections: list[str] = [
            f"Company: {company_name}",
            "",
            "Analyse all the following public intelligence and generate a structured Company Intelligence Summary.",
            "",
        ]

        # ── Website Intelligence ─────────────────────────────────
        if website_texts:
            sections.append("=== WEBSITE INTELLIGENCE ===")
            for item in website_texts:
                page_type = item.get("page_type", "page")
                text = item.get("text", "")
                if text.strip():
                    sections.append(f"\n[{page_type.upper()}]\n{text[:1200]}")
            sections.append("")

        # ── LinkedIn Intelligence ────────────────────────────────
        if linkedin_activities:
            sections.append("=== LINKEDIN INTELLIGENCE ===")
            for activity in linkedin_activities[:8]:
                sections.append(
                    f"- [{activity.get('post_type', 'post').upper()}] {activity.get('headline', '')} | {activity.get('summary', '')[:300]}"
                )
            sections.append("")

        # ── News Intelligence ────────────────────────────────────
        if news_events:
            sections.append("=== PUBLIC NEWS INTELLIGENCE ===")
            for event in news_events[:12]:
                sections.append(
                    f"- [{event.get('event_type', 'news').upper()}] {event.get('headline', '')} | {event.get('summary', '')[:400]}"
                )
            sections.append("")

        sections.append("Generate the complete Company Intelligence Summary JSON now.")
        return "\n".join(sections)
