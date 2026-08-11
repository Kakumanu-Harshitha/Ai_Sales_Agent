"""
Orchestration service — Session 3.1

Full pipeline: Prospect → Store → Signal Scan → Score → Outreach

This is the main entry point that wires all AI agents together.
"""

import logging
from sqlalchemy.orm import Session
from .schemas import RunProspectingRequest, RunProspectingResponse
from apps.api.modules.prospecting.schemas import ProspectingRequest
from apps.api.modules.prospecting.service import ProspectingService
from apps.api.modules.signals.service import SignalsService
from apps.api.modules.outreach.service import OutreachService
from apps.api.modules.crm.models import Lead

logger = logging.getLogger(__name__)


class OrchestrationService:
    def __init__(self):
        self.prospecting = ProspectingService()
        self.signals = SignalsService()
        self.outreach = OutreachService()

    def run_prospecting_pipeline(
        self, db: Session, request: RunProspectingRequest
    ) -> RunProspectingResponse:
        """
        Full sales pipeline orchestration:
        1. Prospecting Agent → discover leads
        2. Signal Detection Agent → scan each lead for buying signals
        3. Outreach Agent → generate outreach for high-score leads
        """
        details = []

        # ── Step 1: Prospect ─────────────────────────────────────────────
        logger.info(f"Step 1: Running prospecting for {request.region}/{request.industry}")

        prospect_req = ProspectingRequest(
            region=request.region,
            industry=request.industry,
            employee_band=request.employee_band,
            keywords=request.keywords,
        )
        prospect_result = self.prospecting.discover_leads(db, prospect_req)

        leads_discovered = len(prospect_result.leads)
        details.append({
            "step": "prospecting",
            "leads_discovered": leads_discovered,
            "status": prospect_result.status,
        })

        if leads_discovered == 0:
            return RunProspectingResponse(
                status="completed",
                leads_discovered=0,
                details=details,
            )

        # ── Step 2: Signal Detection ─────────────────────────────────────
        logger.info(f"Step 2: Running signal detection for {leads_discovered} leads")

        new_leads = (
            db.query(Lead)
            .filter(Lead.status.in_(["new", "scored"]))
            .order_by(Lead.id.desc())
            .limit(leads_discovered)
            .all()
        )

        scored_count = 0
        for lead in new_leads:
            result = self.signals.scan_lead_signals(db, lead.id)
            if not result.get("skipped"):
                scored_count += 1
                details.append({
                    "step": "signal_scan",
                    "lead_id": lead.id,
                    "score": result.get("score"),
                    "priority": result.get("priority"),
                })

        db.commit()

        # ── Step 3: Outreach for High-Score Leads ────────────────────────
        logger.info(f"Step 3: Running outreach for leads with score >= {request.score_threshold}")

        qualified_leads = (
            db.query(Lead)
            .filter(
                Lead.status == "scored",
                Lead.lead_score >= request.score_threshold,
            )
            .all()
        )

        outreach_count = 0
        for lead in qualified_leads:
            signal_summary = f"Lead score: {lead.lead_score}, Priority: {lead.priority}"
            result = self.outreach.generate_initial_outreach(
                db, lead.id, signal_summary=signal_summary
            )
            if not result.get("skipped"):
                outreach_count += 1
                details.append({
                    "step": "outreach",
                    "lead_id": lead.id,
                    "email_id": result.get("email_id"),
                })

        db.commit()

        logger.info(
            f"Pipeline complete: {leads_discovered} discovered, "
            f"{scored_count} scored, {outreach_count} outreach sent"
        )

        return RunProspectingResponse(
            status="completed",
            leads_discovered=leads_discovered,
            leads_scored=scored_count,
            outreach_sent=outreach_count,
            details=details,
        )
