"""
Prospecting module service.

Wires all engine providers together and exposes the job-based
async prospecting pipeline to the router.
"""
import asyncio
import json
import logging
import threading
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from apps.api.modules.prospecting.engine.config import get_settings
from apps.api.modules.prospecting.engine.core.orchestrator import (
    OrchestratorDependencies,
    ProspectingOrchestrator,
)
from apps.api.modules.prospecting.engine.schemas.internal import ICPFilter
from apps.api.modules.prospecting.engine.ai.llm_client import LLMClient
from apps.api.modules.prospecting.engine.providers.apollo_provider import ApolloProvider
from apps.api.modules.prospecting.engine.providers.tavily_provider import TavilyProvider
from apps.api.modules.prospecting.engine.providers.healthcare_directory_provider import HealthcareDirectoryProvider
from apps.api.modules.prospecting.engine.providers.hunter_provider import HunterProvider
from apps.api.modules.prospecting.engine.providers.prospeo_provider import ProspeoProvider
from apps.api.modules.prospecting.engine.providers.overpass_provider import OverpassProvider
from apps.api.modules.prospecting.engine.providers.tinyfish_provider import TinyFishProvider
from apps.api.modules.prospecting.engine.providers.osint_provider import OSINTProvider
from apps.api.modules.prospecting.engine.providers.serper_provider import SerperProvider
from apps.api.modules.prospecting.engine.providers.abstract_provider import AbstractCompanyEnricher
from apps.api.modules.prospecting.engine.services.company_discovery import CompanyDiscoveryService
from apps.api.modules.prospecting.engine.services.company_research import CompanyResearchService
from apps.api.modules.prospecting.engine.services.decision_maker import DecisionMakerDiscoveryService
from apps.api.modules.prospecting.engine.services.deduplication import DeduplicationService
from apps.api.modules.prospecting.engine.services.email_resolver import EmailResolver
from apps.api.modules.prospecting.engine.services.qualification import LeadQualificationService
from apps.api.modules.prospecting.engine.services.verification import VerificationService
from apps.api.modules.prospecting.models import ProspectingJob
from apps.api.modules.prospecting.repository import ProspectingRepository

logger = logging.getLogger(__name__)


def _build_orchestrator() -> ProspectingOrchestrator:
    """
    Factory that wires all providers into the orchestrator.
    Called once per job — providers are lightweight, stateless.
    """
    llm = LLMClient()
    apollo = ApolloProvider()
    tavily = TavilyProvider()
    npi = HealthcareDirectoryProvider()
    hunter = HunterProvider()
    overpass = OverpassProvider()
    tinyfish = TinyFishProvider()
    prospeo = ProspeoProvider()
    osint = OSINTProvider()
    serper = SerperProvider()

    # Discovery pipeline (company finding):
    # 1. NPI Registry — free, authoritative US healthcare registry (organizations)
    # 2. Overpass (OpenStreetMap) — free, rich healthcare amenity types, geo-aware
    # 3. TinyFish — AI web agent search (complementary index to Tavily)
    # 4. Tavily — web search with randomized ICP-aware queries
    # 5. Apollo — backup discovery (disabled on free tier 403s)
    # 6. Serper — Google Maps discovery
    discovery_providers = [npi, overpass, tinyfish, tavily, apollo, serper]

    # Enrichment pipeline (email finding, waterfall):
    # 1. Prospeo — best verification, primary email finder
    # 2. Hunter.io — email finder + verifier
    # 3. OSINT — searches open web for publicly posted emails (free, uses Tavily)
    # 4. Apollo — backup enrichment
    enrichment_providers = [prospeo, hunter, osint, apollo]

    abstract_enricher = AbstractCompanyEnricher()

    deps = OrchestratorDependencies(
        company_discovery=CompanyDiscoveryService(discovery_providers),
        decision_maker_discovery=DecisionMakerDiscoveryService([apollo, tavily, npi]),
        company_research=CompanyResearchService(llm),
        email_resolver=EmailResolver(enrichment_providers),
        verification=VerificationService(),
        deduplication=DeduplicationService(),
        qualification=LeadQualificationService(llm),
        company_enricher=abstract_enricher,
    )
    return ProspectingOrchestrator(deps)





class ProspectingService:
    """
    Exposes the prospecting pipeline to the API router.
    Manages job creation and background execution.
    """

    def __init__(self):
        self.repo = ProspectingRepository()
        self._settings = get_settings()

    def create_search_job(self, db: Session, icp_data: dict) -> ProspectingJob:
        """Create a pending job record and return it."""
        job = ProspectingJob(
            status="pending",
            icp_json=json.dumps(icp_data),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        return job


    async def run_job_async_wrapper(self, job_id: int, icp: ICPFilter) -> None:
        """
        Runs the async orchestrator natively inside FastAPI's event loop via BackgroundTasks.
        """
        from apps.api.db.database import SessionLocal
        db = SessionLocal()
        try:
            orchestrator = _build_orchestrator()
            await orchestrator.run(icp, job_id, db)
        except Exception as exc:
            logger.error("Job crashed for job %s: %s", job_id, exc, exc_info=True)
            try:
                job = db.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = str(exc)
                    job.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()

    def get_job(self, db: Session, job_id: int) -> ProspectingJob | None:
        return db.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()

    def list_jobs(self, db: Session, skip: int = 0, limit: int = 20) -> list[ProspectingJob]:
        return (
            db.query(ProspectingJob)
            .order_by(ProspectingJob.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def save_leads(self, db: Session, leads_data: list[dict]) -> dict:
        """Manual save of user-selected leads (legacy endpoint)."""
        saved = 0
        errors = []
        for ld in leads_data:
            try:
                self.repo.store_discovered_lead(db, ld)
                saved += 1
            except Exception as e:
                logger.error("Failed to save lead %s: %s", ld.get("company_name"), e, exc_info=True)
                errors.append(str(e))
        return {"saved": saved, "errors": errors, "total_requested": len(leads_data)}

    def re_enrich_contact(self, db: Session, contact_id: int) -> dict:
        """
        Second-pass enrichment for a contact with missing or partial email data.

        Called by AgentController when perceive() finds a Contact with no verified
        email / phone, or a CompanyIntelligence record in 'partial' status.

        Reuses the existing EmailResolver waterfall (Hunter → PDL → Apollo →
        SMTP pattern fallback) — all provider ordering and fallback logic stays here.

        Returns:
            {
              "contact_id": int,
              "outcome": "success" | "provider_error" | "rate_limited" | "no_domain",
              "provider": str | None,
              "email_found": bool,
              "email": str | None,
            }
        """
        import asyncio
        from apps.api.modules.crm.models import Contact, Company
        from apps.api.modules.prospecting.engine.schemas.internal import (
            CandidateContact, CandidateCompany, EnrichmentStatus,
        )

        contact = db.query(Contact).filter(Contact.id == contact_id).first()
        if not contact:
            return {
                "contact_id": contact_id,
                "outcome": "provider_error",
                "provider": None,
                "email_found": False,
                "email": None,
            }

        # Resolve company domain
        domain = None
        company_name = "Unknown"
        if contact.company_id:
            company = db.query(Company).filter(Company.id == contact.company_id).first()
            if company:
                company_name = company.name or "Unknown"
                domain = company.domain or (
                    company.website.replace("https://", "").replace("http://", "").rstrip("/")
                    if company.website else None
                )

        if not domain:
            logger.info("re_enrich_contact: no domain for contact %s, skipping", contact_id)
            return {
                "contact_id": contact_id,
                "outcome": "no_domain",
                "provider": None,
                "email_found": False,
                "email": None,
            }

        # Bridge CRM Contact → prospecting engine schema
        candidate_contact = CandidateContact(
            first_name=contact.first_name or "",
            last_name=contact.last_name or "",
            title=contact.title or "",
            linkedin_url=contact.linkedin_url or "",
            source_provider="crm",
        )
        candidate_company = CandidateCompany(
            name=company_name,
            domain=domain,
        )

        # Run the resolver using the same enrichment provider stack
        from apps.api.modules.prospecting.engine.providers.hunter_provider import HunterProvider
        from apps.api.modules.prospecting.engine.providers.prospeo_provider import ProspeoProvider
        from apps.api.modules.prospecting.engine.providers.apollo_provider import ApolloProvider
        from apps.api.modules.prospecting.engine.providers.osint_provider import OSINTProvider
        from apps.api.modules.prospecting.engine.services.email_resolver import EmailResolver

        enrichment_providers = [
            ProspeoProvider(),
            HunterProvider(),
            OSINTProvider(),
            ApolloProvider(),
        ]
        resolver = EmailResolver(enrichment_providers)

        try:
            loop = asyncio.new_event_loop()
            try:
                enriched = loop.run_until_complete(
                    resolver.resolve(candidate_contact, candidate_company)
                )
            finally:
                loop.close()
        except Exception as exc:
            logger.error("re_enrich_contact: resolver raised for contact %s: %s", contact_id, exc, exc_info=True)
            return {
                "contact_id": contact_id,
                "outcome": "provider_error",
                "provider": None,
                "email_found": False,
                "email": None,
            }

        email_found = bool(enriched.email and enriched.email != contact.email)
        outcome = "success" if email_found else "provider_error"

        # Detect rate-limit signal from enrichment status
        if enriched.enrichment_status == EnrichmentStatus.PARTIAL:
            outcome = "rate_limited"

        provider_used = (
            enriched.enrichment_providers_used[0]
            if enriched.enrichment_providers_used else None
        )

        # Persist the new email if one was found
        if email_found:
            contact.email = enriched.email
            if enriched.phone and not contact.phone:
                contact.phone = enriched.phone
            db.commit()
            logger.info(
                "re_enrich_contact: updated contact %s email via %s",
                contact_id, provider_used,
            )

        return {
            "contact_id": contact_id,
            "outcome": outcome,
            "provider": str(provider_used) if provider_used else None,
            "email_found": email_found,
            "email": enriched.email if email_found else None,
        }
