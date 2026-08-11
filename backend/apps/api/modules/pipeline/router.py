"""
Pipeline module — GET /pipeline/report route.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.db.database import get_db
from .schemas import PipelineReportResponse
from .service import PipelineService

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])
service = PipelineService()


@router.get("/report", response_model=PipelineReportResponse)
def get_pipeline_report(db: Session = Depends(get_db)):
    """
    Pipeline report aggregated from PostgreSQL.
    Returns: lead funnel, pipeline forecast, revenue forecast,
    risk flags, stalled deals, campaign performance, conversion rate,
    and next best actions.
    """
    return service.generate_report(db)
