"""
core/orchestrator.py - ProspectingOrchestrator.

Adapted from the standalone prospecting_agent for integration into the
SETV Sales Agent main app. Uses the main app CRM SQLAlchemy session
for persistence instead of async NeonDB.

Pipeline:
  1. Company Discovery (Tavily + NPI Registry + Apollo)
  2. Deduplication
  3. Per-company: Decision Maker Discovery + Research + Enrichment + Verification
  4. Qualification
  5. Persist to CRM tables (Company / Contact / Lead / Activity)
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.schemas.internal import (
    CandidateCompany,
    ICPFilter,
    QualifiedLead,
    LeadConfidenceScore,
)
from apps.api.modules.prospecting.engine.core.icp import apply_hard_gate, build_disqualification_reasons
from apps.api.modules.prospecting.engine.services.company_discovery import CompanyDiscoveryService, DiscoveryStats
from apps.api.modules.prospecting.engine.services.company_research import CompanyResearchService
from apps.api.modules.prospecting.engine.services.decision_maker import DecisionMakerDiscoveryService
from apps.api.modules.prospecting.engine.services.deduplication import DeduplicationService
from apps.api.modules.prospecting.engine.services.email_resolver import EmailResolver
from apps.api.modules.prospecting.engine.services.qualification import LeadQualificationService
from apps.api.modules.prospecting.engine.services.verification import VerificationService
from apps.api.modules.prospecting.engine.services.contact_pool import ContactCandidatePool

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorDependencies:
    company_discovery: CompanyDiscoveryService
    decision_maker_discovery: DecisionMakerDiscoveryService
    company_research: CompanyResearchService
    email_resolver: EmailResolver
    verification: VerificationService
    deduplication: DeduplicationService
    qualification: LeadQualificationService
    company_enricher: object | None = None  # AbstractCompanyEnricher (optional)


@dataclass
class RunStats:
    total_discovered: int = 0
    total_after_dedup: int = 0
    total_qualified: int = 0
    total_persisted: int = 0
    total_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    provider_stats: dict[str, Any] = field(default_factory=dict)


class ProspectingOrchestrator:
    """
    Coordinates the full prospecting pipeline for a single search run.
    Instantiate once per job and call run().
    """

    def __init__(self, deps: OrchestratorDependencies) -> None:
        self._deps = deps
        self._settings = get_settings()
        self._semaphore = asyncio.Semaphore(self._settings.max_concurrent_research)

    async def run(self, icp: ICPFilter, job_id: int, db_session) -> RunStats:
        """
        Execute the full prospecting pipeline.

        Args:
            icp: ICP filter criteria.
            job_id: Integer PK of the ProspectingJob row in the main app DB.
            db_session: SQLAlchemy sync Session (main app).

        Returns:
            RunStats with final counts and any errors.
        """
        from apps.api.modules.prospecting.models import ProspectingJob  # noqa: PLC0415
        stats = RunStats()

        # Mark job as running
        job = db_session.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()
        if job:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db_session.commit()

        logger.info("Prospecting run started (job=%s, max_results=%d)", job_id, icp.max_results)

        try:
            # Phase 1: Company Discovery
            raw_companies, provider_stats = await self._deps.company_discovery.discover(icp)
            stats.total_discovered = len(raw_companies)
            stats.provider_stats = {
                name: {
                    "discovered": s.discovered,
                    "skipped": s.skipped,
                    "skip_reason": s.skip_reason,
                    "errors": s.errors,
                }
                for name, s in provider_stats.items()
            }
            logger.info("Phase 1 complete: %d companies discovered", stats.total_discovered)

            # Phase 2: Deduplication
            unique_companies = self._deps.deduplication.deduplicate_companies(raw_companies)
            stats.total_after_dedup = len(unique_companies)
            companies_to_process = unique_companies[: icp.max_results]
            logger.info("Phase 2 complete: %d unique companies (processing %d)", stats.total_after_dedup, len(companies_to_process))
            
            # Live update job status for discovery
            if job:
                job.total_companies_discovered = stats.total_discovered
                db_session.commit()

            # Phase 3 & 4: Per-Company Processing and Live Persistence
            from apps.api.db.database import SessionLocal
            
            tasks = [self._process_company(company, icp, stats) for company in companies_to_process]
            
            for f in asyncio.as_completed(tasks):
                try:
                    result = await f
                    if result is not None:
                        stats.total_qualified += 1
                        
                        # Use a short-lived session to prevent idle SSL drops from NeonDB
                        with SessionLocal() as short_db:
                            try:
                                self._persist_lead_to_crm(result, short_db, stats)
                                short_db.commit()
                                
                                # Live update job status for qualified & persisted
                                local_job = short_db.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()
                                if local_job:
                                    local_job.total_leads_qualified = stats.total_qualified
                                    local_job.total_leads_persisted = stats.total_persisted
                                    short_db.commit()
                            except Exception as exc:
                                logger.error("Failed to persist lead for '%s': %s", result.company.name, exc, exc_info=True)
                                stats.errors.append(f"Persistence error for '{result.company.name}': {exc}")
                                short_db.rollback()
                            
                except Exception as exc:
                    logger.error("Company processing task raised: %s", exc)
                    stats.errors.append(str(exc))

            logger.info("Phase 3 & 4 complete: %d leads qualified, %d leads persisted", stats.total_qualified, stats.total_persisted)

            # Mark job completed using a fresh session
            if job:
                with SessionLocal() as short_db:
                    final_job = short_db.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()
                    if final_job:
                        final_job.status = "completed"
                        final_job.completed_at = datetime.now(timezone.utc)
                        final_job.total_companies_discovered = stats.total_discovered
                        final_job.total_leads_qualified = stats.total_qualified
                        final_job.total_leads_persisted = stats.total_persisted
                        import json
                        final_job.provider_stats_json = json.dumps(stats.provider_stats)
                        short_db.commit()

            # ── Intelligence Enrichment (background, non-blocking) ─────────
            # After prospecting completes, trigger Company Intelligence Engine
            # for every newly persisted company. Runs asynchronously so it
            # never delays the prospecting pipeline result.
            try:
                from apps.api.modules.crm.models import Company
                from apps.api.modules.intelligence.engine import CompanyIntelligenceEngine

                with SessionLocal() as intel_db:
                    all_companies = intel_db.query(Company).order_by(Company.id.desc()).limit(100).all()
                    company_ids = [c.id for c in all_companies]

                if company_ids:
                    async def _run_intelligence_for_all(ids: list[int]) -> None:
                        engine = CompanyIntelligenceEngine()
                        for cid in ids:
                            try:
                                await engine.enrich(company_id=cid)
                            except Exception as exc:
                                logger.warning("Intelligence enrichment failed for company %d: %s", cid, exc)

                    asyncio.create_task(_run_intelligence_for_all(company_ids))
                    logger.info("Intelligence enrichment scheduled for %d companies in background", len(company_ids))
            except Exception as exc:
                logger.warning("Could not schedule intelligence enrichment: %s", exc)

        except Exception as exc:
            logger.error("Orchestrator run failed (job=%s): %s", job_id, exc, exc_info=True)
            error_msg = f"Orchestrator error: {exc}"
            stats.errors.append(error_msg)
            if job:
                from apps.api.db.database import SessionLocal
                with SessionLocal() as short_db:
                    final_job = short_db.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()
                    if final_job:
                        final_job.status = "failed"
                        final_job.error_message = error_msg
                        final_job.completed_at = datetime.now(timezone.utc)
                        short_db.commit()

        logger.info(
            "Prospecting run complete (job=%s): discovered=%d deduped=%d qualified=%d persisted=%d errors=%d",
            job_id, stats.total_discovered, stats.total_after_dedup,
            stats.total_qualified, stats.total_persisted, len(stats.errors),
        )
        return stats

    async def _process_company(self, company: CandidateCompany, icp: ICPFilter, stats: RunStats) -> QualifiedLead | None:
        async with self._semaphore:
            try:
                return await self._company_pipeline(company, icp)
            except Exception as exc:
                logger.warning("Company '%s' pipeline error: %s", company.name, exc, exc_info=True)
                stats.errors.append(f"Company '{company.name}': {exc}")
                return None

    async def _company_pipeline(self, company: CandidateCompany, icp: ICPFilter) -> QualifiedLead | None:
        # Optional: enrich company data from Abstract API before qualification
        if self._deps.company_enricher is not None:
            try:
                company = await self._deps.company_enricher.enrich(company)
            except Exception as exc:
                logger.debug("Abstract enrichment skipped for '%s': %s", company.name, exc)

        # LANE A: Decision maker discovery & company research in parallel
        dm_task = self._deps.decision_maker_discovery.discover(company, icp)
        research_task = self._deps.company_research.research(company)
        contacts_raw, company_context = await asyncio.gather(dm_task, research_task, return_exceptions=True)

        if isinstance(contacts_raw, Exception):
            logger.warning("Decision maker discovery failed for '%s': %s", company.name, contacts_raw)
            contacts_raw = []

        if isinstance(company_context, Exception):
            logger.warning("Company research failed for '%s': %s", company.name, company_context)
            company_context = None

        contacts_raw = self._deps.deduplication.deduplicate_contacts(contacts_raw)

        pool = ContactCandidatePool(icp)
        pool.add_all(contacts_raw)
        best_candidate = pool.select_best()

        # Generate a placeholder if no contacts were found
        if not best_candidate:
            from apps.api.modules.prospecting.engine.schemas.internal import CandidateContact
            best_candidate = CandidateContact(company_internal_id=company.internal_id, title=None)

        # LANE B: Email Resolution (only for best_candidate)
        resolved_contact = await self._deps.email_resolver.resolve(best_candidate, company)
        verified_contact = await self._deps.verification.verify(resolved_contact)

        # FALLBACK: If no email found, try to use a generic scraped email
        if not verified_contact.email and company_context and company_context.scraped_emails:
            best_scraped = company_context.scraped_emails[0]
            # Prefer generic inboxes
            for e in company_context.scraped_emails:
                if any(prefix in e.lower() for prefix in ["info@", "contact@", "hello@", "admin@", "office@"]):
                    best_scraped = e
                    break
            
            from apps.api.modules.prospecting.engine.schemas.internal import VerificationStatus, EnrichmentStatus
            
            # Update the contact with the fallback generic email
            verified_contact = verified_contact.model_copy(update={
                "email": best_scraped,
                "email_verification_status": VerificationStatus.UNVERIFIED,
                "enrichment_status": EnrichmentStatus.PARTIAL
            })
            
            # If this is a placeholder contact, give it a nice name for the CRM
            sc = verified_contact.source_contact
            if not sc.first_name and not sc.title:
                verified_contact = verified_contact.model_copy(update={
                    "source_contact": sc.model_copy(update={"first_name": "Clinic", "last_name": "Team", "title": "General Contact"})
                })

        primary_contact_raw = verified_contact.source_contact

        # INHERIT COMPANY PHONE
        # If the individual contact doesn't have a direct line, but the company (e.g. from Google Maps)
        # has a main phone number, inherit it so the lead passes qualification and is actionable.
        if not verified_contact.phone and company.phone:
            verified_contact = verified_contact.model_copy(update={"phone": company.phone})
            logger.debug("Inherited company phone number for contact at '%s'", company.name)

        # FACEBOOK FALLBACK HUNT
        # If standard discovery failed to find an email or phone, we do a targeted hunt for
        # their Facebook/social page snippets using Tavily. Facebook snippets often contain pristine contact info.
        if not verified_contact.email and not verified_contact.phone and self._settings.tavily_api_key:
            logger.info("Attempting Facebook fallback hunt for '%s'", company.name)
            try:
                import httpx
                import json
                query = f"{company.name} Facebook page contact email phone number"
                if company.hq_city:
                    query = f"{company.name} {company.hq_city} Facebook page contact"
                
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://api.tavily.com/search",
                        json={"api_key": self._settings.tavily_api_key, "query": query, "search_depth": "basic", "include_answer": False},
                        timeout=10.0
                    )
                    if resp.status_code == 200:
                        results = resp.json().get("results", [])
                        combined_text = "\n".join([r.get("content", "") for r in results[:3]])
                        if combined_text:
                            prompt = f"Extract the email address and phone number for {company.name} from this text. Return JSON with 'email' (null if not found) and 'phone' (null if not found) keys.\nText: {combined_text}"
                            extraction = await self._deps.company_research._researcher._groq.complete(prompt)
                            if extraction:
                                import re
                                cleaned = re.sub(r'```(?:json)?|```', '', extraction.content).strip()
                                try:
                                    data = json.loads(cleaned)
                                except json.JSONDecodeError:
                                    data = {}
                            else:
                                data = {}
                            new_email = data.get("email")
                            new_phone = data.get("phone")
                            if new_email or new_phone:
                                logger.info("Fallback hunt found info for '%s': email=%s, phone=%s", company.name, new_email, new_phone)
                                verified_contact = verified_contact.model_copy(update={
                                    "email": new_email or verified_contact.email,
                                    "phone": new_phone or verified_contact.phone,
                                })
            except Exception as e:
                logger.warning("Facebook fallback hunt failed for '%s': %s", company.name, e)

        # PRE-QUALIFICATION FILTER: Reject leads without ANY reachable contact info.
        # We require either an email address or a phone number.
        if not verified_contact.email and not verified_contact.phone:
            logger.info("Company '%s' rejected before qualification: missing contact info (no email or phone).", company.name)
            return None

        # d: Qualify
        qualification = await self._deps.qualification.qualify(
            company=company,
            contact=primary_contact_raw if primary_contact_raw.title else None,
            icp=icp,
            company_context=company_context,
            enriched=verified_contact,
        )

        qualified, needs_contact_research = apply_hard_gate(
            qualification.score,
            qualification.score_breakdown,
            self._settings.qualification_threshold,
        )

        # Disqualify if both conditions fail
        if not qualified and not needs_contact_research:
            logger.debug("Company '%s' disqualified (score=%d)", company.name, qualification.score)
            return None

        # Update qualification with hard gate results
        disqualification_reasons = [] if qualified else build_disqualification_reasons(
            qualification.score_breakdown, company, primary_contact_raw if primary_contact_raw.title else None, icp
        )

        qualification = qualification.model_copy(
            update={
                "qualified": qualified,
                "needs_contact_research": needs_contact_research,
                "disqualification_reasons": disqualification_reasons,
                "contact_actionability": qualification.score_breakdown.get("contact_actionability", 0),
            }
        )

        logger.info(
            "Company '%s' QUALIFIED (score=%d, needs_research=%s)",
            company.name, qualification.score, needs_contact_research
        )

        # POST-QUALIFICATION DEEP ENRICHMENT
        # Only spend API credits getting deep maps data on leads that passed the gate.
        if qualified and self._settings.serper_api_key:
            logger.info("Performing deep enrichment for qualified lead '%s'", company.name)
            try:
                import httpx
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        "https://google.serper.dev/places",
                        json={"q": f"{company.name} {company.hq_city or ''}".strip(), "gl": "us"},
                        headers={"X-API-KEY": self._settings.serper_api_key, "Content-Type": "application/json"},
                        timeout=10.0
                    )
                    if resp.status_code == 200:
                        places = resp.json().get("places", [])
                        if places:
                            place = places[0]
                            new_phone = place.get("phoneNumber")
                            new_address = place.get("address")
                            rating = place.get("rating")
                            reviews = place.get("ratingCount")
                            
                            if new_phone and not verified_contact.phone:
                                verified_contact = verified_contact.model_copy(update={"phone": new_phone})
                            if new_address:
                                company = company.model_copy(update={"address": new_address})
                            if rating:
                                company = company.model_copy(update={"description": f"{company.description or ''} | Google Rating: {rating} ({reviews} reviews)".strip(" |")})
            except Exception as e:
                logger.warning("Deep enrichment failed for '%s': %s", company.name, repr(e))

        # Build Confidence Score
        # Retrieve score from pool or default to raw properties if generated placeholder
        dm_conf = primary_contact_raw.source_reliability
        if primary_contact_raw.title:
            pool_rank = pool._score(primary_contact_raw)  # Best effort recalculation
            dm_conf = pool_rank.composite

        from apps.api.modules.prospecting.engine.schemas.internal import VerificationStatus
        if verified_contact.email_verification_status == VerificationStatus.VERIFIED:
            email_conf = 100
        elif verified_contact.email:
            email_conf = 60
            if "MANUAL" in [p.value for p in verified_contact.enrichment_providers_used]:
                email_conf = 30 # pattern generated
        else:
            email_conf = 0

        overall_conf = int((qualification.score * 0.5) + (dm_conf * 0.3) + (email_conf * 0.2))

        confidence_score = LeadConfidenceScore(
            icp_score=qualification.score,
            contact_dm_confidence=dm_conf,
            email_confidence=email_conf,
            overall=overall_conf,
        )

        source_providers = list({company.source_provider, primary_contact_raw.source_provider})
        return QualifiedLead(
            company=company,
            contact=verified_contact,
            company_context=company_context,
            qualification=qualification,
            confidence=confidence_score,
            source_providers=source_providers,
        )

    def _persist_lead_to_crm(self, qualified_lead: QualifiedLead, db, stats: RunStats) -> None:
        """Save a qualified lead to the main app's CRM tables."""
        from apps.api.modules.crm.models import Company, Contact, Lead, Activity  # noqa: PLC0415
        from urllib.parse import urlparse  # noqa: PLC0415

        company_data = qualified_lead.company
        contact_enriched = qualified_lead.contact
        contact_raw = contact_enriched.source_contact
        qual = qualified_lead.qualification
        conf = qualified_lead.confidence

        # Upsert Company
        domain = None
        if company_data.domain:
            domain = company_data.domain
        elif company_data.website:
            try:
                parsed = urlparse(company_data.website if "://" in company_data.website else f"https://{company_data.website}")
                domain = parsed.hostname
            except Exception:
                pass

        company = None
        if domain:
            company = db.query(Company).filter(Company.domain == domain).first()
        if not company:
            company = db.query(Company).filter(Company.name == company_data.name).first()
        if not company:
            company = Company(
                name=company_data.name,
                domain=domain,
                industry=company_data.industry,
                website=company_data.website,
                org_type=company_data.industry,
                state=company_data.hq_state,
                city=company_data.hq_city,
                country=company_data.hq_country or "US",
                employee_size=company_data.employee_range,
            )
            db.add(company)
            db.flush()

        # Upsert Contact (allow saving even if only phone is available)
        contact = None
        email = contact_enriched.email
        phone = contact_enriched.phone or company_data.phone

        if email:
            contact = db.query(Contact).filter(Contact.email == email).first()
        elif phone:
            contact = db.query(Contact).filter(Contact.phone == phone).first()

        if not contact:
            name = contact_raw.display_name or "Unknown Contact"
            parts = name.split(" ", 1)
            
            # The database schema strictly requires an email for every contact.
            # If we qualified the lead via phone only, inject a placeholder email.
            safe_email = email
            if not safe_email:
                unique_id = uuid.uuid4().hex[:8]
                safe_email = f"no-email-{unique_id}@no-email-provided.local"
                
            contact = Contact(
                company_id=company.id,
                first_name=parts[0] if parts else None,
                last_name=parts[1] if len(parts) > 1 else None,
                email=safe_email,
                phone=phone,
                title=contact_raw.title or "General Contact",
                linkedin_url=contact_enriched.linkedin_url,
            )
            db.add(contact)
            db.flush()
        # Prevent duplicate leads for existing contacts
        existing_lead = db.query(Lead).filter(Lead.contact_id == contact.id).first()
        if existing_lead:
            logger.info("Skipping lead for %s: Contact %s already exists in the CRM as a Lead.", company.name, email)
            return

        # Create Lead
        # Determine CRM status
        crm_status = "qualified_needs_contact_research" if qual.needs_contact_research else "new"

        lead = Lead(
            contact_id=contact.id,
            status=crm_status,
            lead_score=float(qual.score),
            priority="high" if qual.score >= 70 else "medium" if qual.score >= 50 else "low",
            source=f"prospecting_agent:{','.join(str(p.value) for p in qualified_lead.source_providers)}",
            stage_entered_at=datetime.utcnow(),
            last_activity_at=datetime.utcnow(),
        )
        db.add(lead)
        db.flush()

        # Activity log
        activity = Activity(
            lead_id=lead.id,
            type="Lead Created",
            description=(
                f"Discovered via Prospecting Agent: {company_data.name} "
                f"| {company_data.industry or 'Healthcare'} "
                f"| Score: {qual.score}/100 "
                f"| Confidence: {conf.overall}/100 " if conf else ""
                f"| Sources: {', '.join(str(p.value) for p in qualified_lead.source_providers)}"
            ),
        )
        db.add(activity)
        db.flush()

        stats.total_persisted += 1
        logger.debug("Persisted lead for '%s' (lead_id=%s) status=%s", company_data.name, lead.id, crm_status)

