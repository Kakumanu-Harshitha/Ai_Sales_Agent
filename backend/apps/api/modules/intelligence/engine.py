"""
Company Intelligence Engine — Core Orchestrator.

Coordinates the full intelligence enrichment pipeline for a single company:

  1. Website Scraping (homepage + subpages)
  2. LinkedIn Intelligence (via search APIs)
  3. News Intelligence (via Tavily / Serper)
  4. AI Synthesis (structured Company Intelligence Summary)
  5. Database Persistence (all insights + AI summary)

Design principles:
  - Fully async
  - Each source is isolated — one failing source never blocks others
  - Historical records are preserved (no overwrites)
  - Refresh strategy: 7-day interval by default, configurable per record
  - Thread-safe DB session management (short-lived sessions per write)
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class CompanyIntelligenceEngine:
    """
    Orchestrates company intelligence enrichment.
    Call `.enrich(company_id)` from anywhere in the codebase.
    """

    def __init__(self):
        from apps.api.modules.intelligence.scrapers.website_scraper import WebsiteScraper
        from apps.api.modules.intelligence.scrapers.linkedin_scraper import LinkedinScraper
        from apps.api.modules.intelligence.scrapers.news_scraper import NewsScraper
        from apps.api.modules.intelligence.ai_synthesizer import AISynthesizer

        self._website_scraper = WebsiteScraper()
        self._linkedin_scraper = LinkedinScraper()
        self._news_scraper = NewsScraper()
        self._synthesizer = AISynthesizer()

    async def enrich(self, company_id: int, force_refresh: bool = False) -> bool:
        """
        Run the full intelligence pipeline for a company.

        Args:
            company_id: The CRM Company.id
            force_refresh: If True, bypass the 7-day refresh interval

        Returns:
            True if enrichment completed (even partially), False on fatal error
        """
        from apps.api.db.database import SessionLocal
        from apps.api.modules.crm.models import Company
        from apps.api.modules.intelligence.models import CompanyIntelligence

        # ── Load company + check refresh interval ────────────────
        with SessionLocal() as db:
            company = db.query(Company).filter(Company.id == company_id).first()
            if not company:
                logger.error("Intelligence enrich: Company %d not found", company_id)
                return False

            company_name = company.name or "Unknown"
            company_website = company.website or company.domain
            company_id_val = company.id

            # Get or create intelligence record
            intel = db.query(CompanyIntelligence).filter(
                CompanyIntelligence.company_id == company_id_val
            ).first()

            if intel is None:
                intel = CompanyIntelligence(
                    company_id=company_id_val,
                    company_website=company_website,
                    status="pending",
                )
                db.add(intel)
                db.commit()
                db.refresh(intel)

            # Check refresh interval (default 7 days)
            if not force_refresh and intel.last_refreshed_at:
                interval_days = intel.refresh_interval_days or 7
                next_refresh = intel.last_refreshed_at + timedelta(days=interval_days)
                if datetime.now(timezone.utc) < next_refresh:
                    logger.info(
                        "Skipping intelligence refresh for company %d — next refresh at %s",
                        company_id_val, next_refresh.isoformat()
                    )
                    return True

            # Mark as running
            intel.status = "running"
            db.commit()
            intel_id = intel.id

        logger.info("Starting intelligence enrichment for '%s' (id=%d)", company_name, company_id_val)

        # ── Run all scrapers concurrently ───────────────────────
        website_task = self._website_scraper.scrape(company_website or "")
        linkedin_task = self._linkedin_scraper.scrape(company_name)
        news_task = self._news_scraper.scrape(company_name, domain=company_website)

        website_pages, linkedin_activities, news_events = await asyncio.gather(
            website_task, linkedin_task, news_task,
            return_exceptions=True
        )

        # Gracefully handle individual scraper failures
        if isinstance(website_pages, Exception):
            logger.warning("Website scraper raised for '%s': %s", company_name, website_pages)
            website_pages = []
        if isinstance(linkedin_activities, Exception):
            logger.warning("LinkedIn scraper raised for '%s': %s", company_name, linkedin_activities)
            linkedin_activities = []
        if isinstance(news_events, Exception):
            logger.warning("News scraper raised for '%s': %s", company_name, news_events)
            news_events = []

        # ── Persist website insights ──────────────────────────────
        await self._persist_website_insights(intel_id, website_pages)

        # ── Persist LinkedIn insights ─────────────────────────────
        await self._persist_linkedin_insights(intel_id, linkedin_activities)

        # ── Persist news insights ─────────────────────────────────
        await self._persist_news_insights(intel_id, news_events)

        # ── AI Synthesis ─────────────────────────────────────────
        website_text_dicts = [
            {"page_type": p.page_type, "text": p.raw_text}
            for p in website_pages if p.success and p.raw_text
        ]
        linkedin_dicts = [
            {"post_type": a.post_type, "headline": a.headline, "summary": a.summary}
            for a in linkedin_activities
        ]
        news_dicts = [
            {"event_type": e.event_type, "headline": e.headline, "summary": e.summary}
            for e in news_events
        ]

        ai_summary = None
        if website_text_dicts or linkedin_dicts or news_dicts:
            try:
                ai_summary = self._synthesizer.synthesize(
                    company_name=company_name,
                    website_texts=website_text_dicts,
                    linkedin_activities=linkedin_dicts,
                    news_events=news_dicts,
                )
            except Exception as exc:
                logger.error("AI synthesis failed for '%s': %s", company_name, exc)

        # ── Persist AI Summary ────────────────────────────────────
        if ai_summary:
            await self._persist_ai_summary(intel_id, ai_summary)

        # ── Mark as completed ─────────────────────────────────────
        status = "completed" if (website_pages or linkedin_activities or news_events) else "partial"
        with SessionLocal() as db:
            from apps.api.modules.intelligence.models import CompanyIntelligence
            intel = db.query(CompanyIntelligence).filter(CompanyIntelligence.id == intel_id).first()
            if intel:
                intel.status = status
                intel.last_refreshed_at = datetime.now(timezone.utc)
                intel.next_refresh_at = datetime.now(timezone.utc) + timedelta(days=intel.refresh_interval_days or 7)
                db.commit()

        logger.info(
            "Intelligence enrichment '%s' status=%s | pages=%d linkedin=%d news=%d ai=%s",
            company_name, status, len(website_pages), len(linkedin_activities),
            len(news_events), "yes" if ai_summary else "no"
        )
        return True

    # ── Persistence helpers ──────────────────────────────────────

    async def _persist_website_insights(self, intel_id: int, pages: list) -> None:
        """Persist scraped website pages to the database."""
        if not pages:
            return
        from apps.api.db.database import SessionLocal
        from apps.api.modules.intelligence.models import WebsiteInsight

        with SessionLocal() as db:
            for page in pages:
                if not page.success or not page.raw_text:
                    continue
                insight = WebsiteInsight(
                    intelligence_id=intel_id,
                    page_type=page.page_type,
                    page_url=page.page_url,
                    page_title=page.page_title,
                    raw_text=page.raw_text,
                )
                db.add(insight)
            db.commit()
        logger.debug("Persisted %d website insights for intel_id=%d", len(pages), intel_id)

    async def _persist_linkedin_insights(self, intel_id: int, activities: list) -> None:
        """Persist LinkedIn activity insights to the database."""
        if not activities:
            return
        from apps.api.db.database import SessionLocal
        from apps.api.modules.intelligence.models import LinkedinInsight

        with SessionLocal() as db:
            for a in activities:
                insight = LinkedinInsight(
                    intelligence_id=intel_id,
                    post_type=a.post_type,
                    headline=a.headline,
                    summary=a.summary,
                    source_url=a.source_url,
                    published_date=a.published_date,
                    raw_text=a.raw_text,
                    is_hiring=a.is_hiring,
                    is_expansion=a.is_expansion,
                    is_ai_initiative=a.is_ai_initiative,
                    is_healthcare_initiative=a.is_healthcare_initiative,
                    is_partnership=a.is_partnership,
                    is_award=a.is_award,
                )
                db.add(insight)
            db.commit()
        logger.debug("Persisted %d linkedin insights for intel_id=%d", len(activities), intel_id)

    async def _persist_news_insights(self, intel_id: int, events: list) -> None:
        """Persist news insights to the database."""
        if not events:
            return
        from apps.api.db.database import SessionLocal
        from apps.api.modules.intelligence.models import NewsInsight

        with SessionLocal() as db:
            for e in events:
                insight = NewsInsight(
                    intelligence_id=intel_id,
                    event_type=e.event_type,
                    headline=e.headline,
                    summary=e.summary,
                    source_name=e.source_name,
                    source_url=e.source_url,
                    published_date=e.published_date,
                    relevance_score=e.relevance_score,
                    raw_text=e.raw_text,
                )
                db.add(insight)
            db.commit()
        logger.debug("Persisted %d news insights for intel_id=%d", len(events), intel_id)

    async def _persist_ai_summary(self, intel_id: int, summary: dict) -> None:
        """Persist the AI-generated Company Intelligence Summary."""
        from apps.api.db.database import SessionLocal
        from apps.api.modules.intelligence.models import AICompanySummary

        def _to_json(val) -> str | None:
            if isinstance(val, list):
                return json.dumps(val)
            return val

        with SessionLocal() as db:
            # Mark all previous summaries as non-latest
            db.query(AICompanySummary).filter(
                AICompanySummary.intelligence_id == intel_id,
                AICompanySummary.is_latest == True
            ).update({"is_latest": False})

            ai_record = AICompanySummary(
                intelligence_id=intel_id,
                is_latest=True,
                company_overview=summary.get("company_overview"),
                business_model=summary.get("business_model"),
                industry=summary.get("industry"),
                core_products_services=_to_json(summary.get("core_products_services")),
                current_priorities=summary.get("current_priorities"),
                business_goals=summary.get("business_goals"),
                technology_focus=summary.get("technology_focus"),
                healthcare_focus=summary.get("healthcare_focus"),
                ai_initiatives=summary.get("ai_initiatives"),
                digital_transformation=summary.get("digital_transformation"),
                innovation_areas=_to_json(summary.get("innovation_areas")),
                recent_initiatives=summary.get("recent_initiatives"),
                expansion_plans=summary.get("expansion_plans"),
                global_presence=summary.get("global_presence"),
                research_programs=summary.get("research_programs"),
                hiring_activity=summary.get("hiring_activity"),
                potential_challenges=summary.get("potential_challenges"),
                possible_opportunities=summary.get("possible_opportunities"),
                buying_signals_detected=_to_json(summary.get("buying_signals_detected")),
                intelligence_completeness=summary.get("intelligence_completeness"),
            )
            db.add(ai_record)
            db.commit()
        logger.info("AI Company Summary persisted for intel_id=%d", intel_id)
