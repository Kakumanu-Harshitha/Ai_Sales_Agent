"""
Company Intelligence API Router.

Endpoints:
  GET  /intelligence/company/{company_id}         — Get full intelligence profile
  POST /intelligence/company/{company_id}/refresh — Trigger manual refresh
  GET  /intelligence/summary/{company_id}         — Get latest AI summary only
  GET  /intelligence/company/{company_id}/news    — Get news insights
  GET  /intelligence/company/{company_id}/linkedin — Get LinkedIn insights
  GET  /intelligence/company/{company_id}/website — Get website insights
"""

import asyncio
import logging
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from apps.api.db.database import get_db
from apps.api.modules.intelligence.models import (
    CompanyIntelligence, WebsiteInsight, LinkedinInsight, NewsInsight, AICompanySummary
)
from apps.api.modules.intelligence.schemas import (
    CompanyIntelligenceOut, AICompanySummaryOut,
    WebsiteInsightOut, LinkedinInsightOut, NewsInsightOut,
)

router = APIRouter(prefix="/intelligence", tags=["Company Intelligence"])
logger = logging.getLogger(__name__)


def _get_intel(db: Session, company_id: int) -> CompanyIntelligence | None:
    return db.query(CompanyIntelligence).filter(
        CompanyIntelligence.company_id == company_id
    ).first()


@router.get("/company/{company_id}", response_model=CompanyIntelligenceOut)
def get_company_intelligence(company_id: int, db: Session = Depends(get_db)):
    """Return the full intelligence profile for a company."""
    intel = _get_intel(db, company_id)
    if not intel:
        raise HTTPException(status_code=404, detail="No intelligence profile found for this company.")

    # Get latest AI summary
    ai_summary = (
        db.query(AICompanySummary)
        .filter(AICompanySummary.intelligence_id == intel.id, AICompanySummary.is_latest == True)
        .first()
    )

    # Build response dict
    result = {
        "id": intel.id,
        "company_id": intel.company_id,
        "status": intel.status,
        "last_refreshed_at": intel.last_refreshed_at,
        "next_refresh_at": intel.next_refresh_at,
        "company_website": intel.company_website,
        "linkedin_url": intel.linkedin_url,
        "website_insights": intel.website_insights,
        "linkedin_insights": intel.linkedin_insights,
        "news_insights": intel.news_insights,
        "ai_summary": ai_summary,
        "created_at": intel.created_at,
    }
    return result


@router.post("/company/{company_id}/refresh")
async def refresh_company_intelligence(
    company_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger a manual intelligence refresh for a company.
    The enrichment runs in the background and returns immediately.
    """
    # Verify company exists
    from apps.api.modules.crm.models import Company
    company = db.query(Company).filter(Company.id == company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found.")

    background_tasks.add_task(_run_enrichment, company_id, force_refresh=True)
    return {"status": "refresh_started", "company_id": company_id}


@router.get("/summary/{company_id}", response_model=AICompanySummaryOut)
def get_ai_summary(company_id: int, db: Session = Depends(get_db)):
    """Return only the latest AI Company Intelligence Summary."""
    intel = _get_intel(db, company_id)
    if not intel:
        raise HTTPException(status_code=404, detail="No intelligence profile found.")
    ai_summary = (
        db.query(AICompanySummary)
        .filter(AICompanySummary.intelligence_id == intel.id, AICompanySummary.is_latest == True)
        .first()
    )
    if not ai_summary:
        raise HTTPException(status_code=404, detail="AI summary not yet generated.")
    return ai_summary


@router.get("/company/{company_id}/news", response_model=list[NewsInsightOut])
def get_news_insights(company_id: int, limit: int = 20, db: Session = Depends(get_db)):
    """Return recent news insights for a company."""
    intel = _get_intel(db, company_id)
    if not intel:
        return []
    news = (
        db.query(NewsInsight)
        .filter(NewsInsight.intelligence_id == intel.id)
        .order_by(NewsInsight.relevance_score.desc())
        .limit(limit)
        .all()
    )
    return news


@router.get("/company/{company_id}/linkedin", response_model=list[LinkedinInsightOut])
def get_linkedin_insights(company_id: int, limit: int = 20, db: Session = Depends(get_db)):
    """Return LinkedIn insights for a company."""
    intel = _get_intel(db, company_id)
    if not intel:
        return []
    return (
        db.query(LinkedinInsight)
        .filter(LinkedinInsight.intelligence_id == intel.id)
        .order_by(LinkedinInsight.scraped_at.desc())
        .limit(limit)
        .all()
    )


@router.get("/company/{company_id}/website", response_model=list[WebsiteInsightOut])
def get_website_insights(company_id: int, db: Session = Depends(get_db)):
    """Return website page insights for a company."""
    intel = _get_intel(db, company_id)
    if not intel:
        return []
    return (
        db.query(WebsiteInsight)
        .filter(WebsiteInsight.intelligence_id == intel.id)
        .order_by(WebsiteInsight.scraped_at.desc())
        .all()
    )


# ── Background helper ─────────────────────────────────────────────────────────

async def _run_enrichment(company_id: int, force_refresh: bool = False) -> None:
    """Wrapper to run the intelligence engine from a background task."""
    try:
        from apps.api.modules.intelligence.engine import CompanyIntelligenceEngine
        engine = CompanyIntelligenceEngine()
        await engine.enrich(company_id=company_id, force_refresh=force_refresh)
    except Exception as exc:
        logger.error("Background intelligence enrichment failed for company %d: %s", company_id, exc)
