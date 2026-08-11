"""
Prospecting module router.

Endpoints:
  POST /prospecting/search        - Trigger async job (returns job_id immediately)
  GET  /prospecting/jobs/{job_id} - Poll job status
  GET  /prospecting/jobs          - List all jobs
  POST /prospecting/save          - Manual lead save (legacy)
"""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session

from apps.api.db.database import get_db, SessionLocal
from apps.api.modules.prospecting.schemas import (
    ProspectingSearchRequest,
    SearchJobResponse,
    JobStatusResponse,
    SaveLeadsRequest,
    SaveLeadsResponse,
)
from apps.api.modules.prospecting.service import ProspectingService
from apps.api.modules.prospecting.engine.schemas.internal import ICPFilter
from apps.api.modules.prospecting.engine.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/prospecting", tags=["Prospecting"])
_service = ProspectingService()


# ── POST /prospecting/search ──────────────────────────────────────────────────

@router.post(
    "/search",
    response_model=SearchJobResponse,
    status_code=202,
    summary="Trigger async prospecting search",
)
def search_prospects(request: ProspectingSearchRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Accept ICP criteria and start an async prospecting run.
    Returns a job_id immediately. Poll GET /prospecting/jobs/{job_id} for status.
    Results will appear in GET /leads once the job completes.
    """
    settings = get_settings()

    icp = ICPFilter(
        industries=request.industries,
        keywords=request.keywords,
        target_roles=request.target_roles,
        regions=request.regions,
        company_size_min=request.company_size_min,
        company_size_max=request.company_size_max,
        technologies=request.technologies,
        max_results=min(request.max_results, settings.max_companies_per_search),
    )

    icp_data = {
        "industries": request.industries,
        "keywords": request.keywords,
        "regions": request.regions,
        "max_results": request.max_results,
    }

    job = _service.create_search_job(db, icp_data)

    logger.info(
        "Prospecting job %s created (industries=%s, regions=%s)",
        job.id, request.industries, request.regions,
    )

    # Start the pipeline in a FastAPI background task natively
    background_tasks.add_task(_service.run_job_async_wrapper, job.id, icp)

    return SearchJobResponse(
        job_id=job.id,
        status="pending",
        message=f"Prospecting search started. Poll /prospecting/jobs/{job.id} for status.",
        created_at=job.created_at,
    )


# ── GET /prospecting/jobs/{job_id} ────────────────────────────────────────────

@router.get(
    "/jobs/{job_id}",
    response_model=JobStatusResponse,
    summary="Get search job status",
)
def get_job_status(job_id: int, db: Session = Depends(get_db)):
    """Poll this after POST /prospecting/search to check progress."""
    job = _service.get_job(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found.")

    provider_stats = {}
    if job.provider_stats_json:
        try:
            provider_stats = json.loads(job.provider_stats_json)
        except Exception:
            pass

    discovered_companies = []
    if job.discovered_companies_json:
        try:
            discovered_companies = json.loads(job.discovered_companies_json)
        except Exception:
            pass
            
    icp_json = {}
    if job.icp_json:
        try:
            icp_json = json.loads(job.icp_json)
        except Exception:
            pass

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        total_companies_discovered=job.total_companies_discovered or 0,
        total_leads_qualified=job.total_leads_qualified or 0,
        total_leads_persisted=job.total_leads_persisted or 0,
        error_message=job.error_message,
        provider_stats=provider_stats,
        discovered_companies=discovered_companies,
        icp_json=icp_json,
    )


# ── GET /prospecting/jobs ─────────────────────────────────────────────────────

@router.get(
    "/jobs",
    summary="List all prospecting jobs",
)
def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List recent prospecting jobs, newest first."""
    jobs = _service.list_jobs(db, skip=skip, limit=limit)
    out_jobs = []
    for j in jobs:
        icp = {}
        if j.icp_json:
            try: icp = json.loads(j.icp_json)
            except: pass
            
        comps = []
        if j.discovered_companies_json:
            try: comps = json.loads(j.discovered_companies_json)
            except: pass
            
        out_jobs.append({
            "job_id": j.id,
            "status": j.status,
            "created_at": j.created_at,
            "completed_at": j.completed_at,
            "total_leads_persisted": j.total_leads_persisted or 0,
            "total_companies_discovered": j.total_companies_discovered or 0,
            "icp_json": icp,
            "discovered_companies": comps,
        })
        
    return {
        "jobs": out_jobs,
        "total": len(jobs),
    }


# ── POST /prospecting/save ────────────────────────────────────────────────────

@router.post(
    "/save",
    response_model=SaveLeadsResponse,
    summary="Manually save selected leads to CRM",
)
def save_leads(request: SaveLeadsRequest, db: Session = Depends(get_db)):
    """
    Save user-selected leads to CRM. Called from the UI after reviewing
    prospecting results from the discover endpoint.
    """
    result = _service.save_leads(db, request.leads)
    return SaveLeadsResponse(
        saved=result["saved"],
        total_requested=result["total_requested"],
        errors=result["errors"],
    )
