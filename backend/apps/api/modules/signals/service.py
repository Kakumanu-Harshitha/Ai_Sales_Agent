"""
Signals module — business logic for signal scanning.

When OPENROUTER_API_KEY is set, uses the real Signal Detection Agent.
Otherwise falls back to stub signal generation.
"""

import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .repository import SignalsRepository
from apps.api.core.idempotency import check_and_mark
from apps.api.core.ai_provider import AIProvider
from apps.api.core.tavily_provider import TavilyProvider
from apps.api.modules.crm.models import Lead

logger = logging.getLogger(__name__)

SIGNAL_DETECTION_SYSTEM = """You are a highly advanced Sales Intelligence Agent for SETV, a healthcare B2B sales system.
Your goal is to detect real, highly-actionable buying signals and provide structured intelligence.

IMPORTANT CONSTRAINTS:
- Do NOT invent signals. Use real public data.
- If no reliable signal is found, return an empty signals array and explain that in the reasoning.

Return a JSON object with:
- company_name
- buying_signal_summary
- lead_score (0-100)
- priority (low/medium/high)
- reasoning
- signals (array of signal objects)

Each signal object MUST contain:
- signal_type: category (e.g., 'Expansion', 'Hiring', 'Funding', 'Technology Change')
- headline: short actionable summary (e.g., 'Hiring 5 new AI Engineers')
- description: detailed description of the event
- business_impact: how this affects their business operations or bottom line
- why_it_matters: why this specific signal matters to SETV (our product)
- source_name: name of the source (e.g., 'LinkedIn', 'Press Release')
- source_url: URL to the source
- source_type: type of source (e.g., 'news', 'job_board', 'social_media')
- published_date: ISO 8601 date string if known
- confidence_score: (0-100) how reliable this signal is
- score_contribution: (0-100) how much this adds to the overall lead score
- recommended_action: what the salesperson should do next
- suggested_pitch: a 1-sentence angle for outreach
- target_persona: the best role/title to contact
- icp_match: (0-100) how well they match our Ideal Customer Profile based on this signal
"""


class SignalsService:
    def __init__(self):
        self.repo = SignalsRepository()

    def scan_lead_signals(self, db: Session, lead_id: int) -> dict:
        """
        Scan a lead for buying signals. Uses idempotency to prevent
        re-scanning within the same calendar day.
        """
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        already_done = check_and_mark(db, "signal_scan", str(lead_id), today)
        if already_done:
            logger.info(f"Signal scan for lead {lead_id} already done today, skipping.")
            return {"skipped": True, "lead_id": lead_id}

        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            logger.warning(f"Lead {lead_id} not found for signal scan.")
            return {"skipped": True, "lead_id": lead_id, "reason": "not_found"}

        # Get company context for the AI call
        company_name = "Unknown"
        website = None
        company_id = None
        if lead.contact_id:
            from apps.api.modules.crm.models import Contact, Company
            contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
            if contact and contact.company_id:
                company = db.query(Company).filter(Company.id == contact.company_id).first()
                if company:
                    company_name = company.name or "Unknown"
                    website = company.website or company.domain
                    company_id = company.id

        # Load Company Intelligence context if available
        intelligence_context = self._load_intelligence_context(db, company_id) if company_id else ""

        # Try real AI call
        signal_data = self._call_signal_agent(company_name, website, intelligence_context)

        if signal_data and signal_data.get("signals"):
            # Real AI signals
            signals_list = signal_data["signals"]
            score = signal_data.get("lead_score", 50)
            priority = signal_data.get("priority", "medium")
        else:
            # Stub fallback
            signals_list = [{
                "signal_type": "Automated Scan",
                "headline": f"Automated Scan for {company_name}",
                "description": f"Automated signal scan on {today}. Configure OPENROUTER_API_KEY for real AI detection.",
                "business_impact": "None",
                "why_it_matters": "Fallback signal generation.",
                "confidence_score": 50.0,
                "score_contribution": 0.0,
                "target_persona": "IT Director",
                "icp_match": 50.0,
                "recommended_action": "Manually research lead",
            }]
            score = 50.0
            priority = "medium"

        created_signals = []
        from .schemas import SignalCreate
        for sig in signals_list:
            sig_data = SignalCreate(
                lead_id=lead_id,
                signal_type=sig.get("signal_type") or sig.get("type", "unknown"),
                headline=sig.get("headline", "Detected Signal"),
                description=sig.get("description", sig.get("evidence", "Signal detected.")),
                business_impact=sig.get("business_impact"),
                why_it_matters=sig.get("why_it_matters"),
                source_name=sig.get("source_name"),
                source_url=sig.get("source_url") or sig.get("evidence_url"),
                source_type=sig.get("source_type"),
                confidence_score=float(sig.get("confidence_score", sig.get("strength", 0.0))),
                score_contribution=float(sig.get("score_contribution", 0.0)),
                priority=sig.get("priority"),
                recommended_action=sig.get("recommended_action"),
                suggested_pitch=sig.get("suggested_pitch"),
                target_persona=sig.get("target_persona"),
                icp_match=float(sig.get("icp_match", 0.0)) if sig.get("icp_match") is not None else None,
            )
            pub_date = sig.get("published_date")
            if pub_date:
                try:
                    sig_data.published_date = datetime.fromisoformat(pub_date.replace("Z", "+00:00"))
                except ValueError:
                    pass

            signal = self.repo.create_signal(db, sig_data)
            created_signals.append(signal)

        self.repo.create_lead_score(db, lead_id, float(score))

        # Update lead
        lead.lead_score = float(score)
        lead.priority = priority
        if lead.status == "new":
            lead.status = "scored"
            lead.stage_entered_at = datetime.now(timezone.utc)
        lead.last_activity_at = datetime.now(timezone.utc)

        self.repo.create_activity(
            db, lead_id, "Signals Detected",
            f"Signal scan completed. Score: {score}. Priority: {priority}. "
            f"Signals: {len(created_signals)}"
        )

        db.flush()

        return {
            "skipped": False,
            "lead_id": lead_id,
            "signals_created": len(created_signals),
            "score": float(score),
            "priority": priority,
        }

    def _load_intelligence_context(self, db: Session, company_id: int) -> str:
        """Load the latest AI Company Intelligence Summary for context injection."""
        try:
            from apps.api.modules.intelligence.models import CompanyIntelligence, AICompanySummary
            intel = db.query(CompanyIntelligence).filter(
                CompanyIntelligence.company_id == company_id
            ).first()
            if not intel:
                return ""
            summary = db.query(AICompanySummary).filter(
                AICompanySummary.intelligence_id == intel.id,
                AICompanySummary.is_latest == True
            ).first()
            if not summary:
                return ""

            parts = []
            if summary.company_overview:
                parts.append(f"Company Overview: {summary.company_overview}")
            if summary.current_priorities:
                parts.append(f"Current Priorities: {summary.current_priorities}")
            if summary.technology_focus:
                parts.append(f"Technology Focus: {summary.technology_focus}")
            if summary.healthcare_focus:
                parts.append(f"Healthcare Focus: {summary.healthcare_focus}")
            if summary.ai_initiatives:
                parts.append(f"AI Initiatives: {summary.ai_initiatives}")
            if summary.expansion_plans:
                parts.append(f"Expansion Plans: {summary.expansion_plans}")
            if summary.hiring_activity:
                parts.append(f"Hiring Activity: {summary.hiring_activity}")
            if summary.buying_signals_detected:
                parts.append(f"Pre-detected Signals: {summary.buying_signals_detected}")
            if summary.recent_initiatives:
                parts.append(f"Recent Initiatives: {summary.recent_initiatives}")

            return "\n".join(parts) if parts else ""
        except Exception as exc:
            logger.debug("Failed to load intelligence context: %s", exc)
            return ""

    def _call_signal_agent(self, company_name: str, website: str | None, intelligence_context: str = "") -> dict:
        """Call the Signal Detection Agent."""
        prompt = f"""Analyze real public data and detect buying signals.
Company: {company_name}
Website: {website or "Not provided"}
"""
        if intelligence_context:
            prompt += f"""
--- COMPANY INTELLIGENCE PROFILE ---
{intelligence_context}
------------------------------------
"""

        prompt += """
Detect buying signals such as:
- Hiring AI Engineers / Data Scientists
- Digital Transformation initiatives
- AI Initiatives
- Hospital Expansion
- Funding rounds
- Press Releases
- Technology Partnerships
- Cloud Adoption

Current Date/Time: """ + datetime.now(timezone.utc).isoformat()

        tavily = TavilyProvider()
        search_context = ""
        if tavily.is_configured():
            logger.info(f"Fetching live context from Tavily for {company_name}...")
            search_query = f"{company_name} recent news OR press release OR funding OR partnership"
            search_results = tavily.search(search_query, max_results=5)
            search_context = f"\n\n--- REAL-TIME SEARCH RESULTS ---\nUse the following verified search results to extract buying signals:\n{search_results}\n--------------------------------\n"
            logger.info("Tavily search context appended.")

        final_prompt = prompt + search_context

        return AIProvider().generate_content(
            system_instruction=SIGNAL_DETECTION_SYSTEM,
            prompt=final_prompt
        )

    def scan_all_eligible_leads(self, db: Session) -> list[dict]:
        """Scan all leads in 'new' or 'scored' status."""
        eligible_leads = (
            db.query(Lead)
            .filter(Lead.status.in_(["new", "scored"]))
            .all()
        )
        results = []
        for lead in eligible_leads:
            result = self.scan_lead_signals(db, lead.id)
            results.append(result)
        return results
