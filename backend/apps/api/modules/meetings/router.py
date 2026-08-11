import logging
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime
from apps.api.db.database import get_db
from .schemas import BookMeetingRequest, BookMeetingResponse, MeetingListResponse
from .service import MeetingsService
from apps.api.modules.crm.models import Meeting

router = APIRouter(prefix="/calendar", tags=["Calendar"])
service = MeetingsService()
logger = logging.getLogger(__name__)


@router.get("/slots")
def get_free_slots(
    account_id: int,
    start_date: datetime,
    end_date: datetime,
    db: Session = Depends(get_db)
):
    return service.get_free_slots(db, account_id, start_date, end_date)


@router.post("/book", response_model=BookMeetingResponse)
def book_meeting(request: BookMeetingRequest, db: Session = Depends(get_db)):
    logger.info(f"[ROUTER] Book meeting request: lead_id={request.lead_id}, contact_id={request.contact_id}, email={request.contact_email}, start={request.slot_start}")
    result = service.book_meeting(
        db=db,
        account_id=request.account_id,
        contact_id=request.contact_id,
        contact_email=request.contact_email or '',
        slot_start=request.slot_start,
        slot_end=request.slot_end or request.slot_start,
        title=request.title,
        description=request.description or '',
        lead_id=request.lead_id,
        timezone=request.timezone,
    )
    db.commit()
    logger.info(f"[ROUTER] Meeting committed. Result: {result}")
    return result


@router.get("/meetings", response_model=MeetingListResponse)
def list_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all meetings ordered by most recent."""
    query = db.query(Meeting)
    total = query.count()
    meetings = query.order_by(Meeting.scheduled_at.desc().nullslast()).offset(skip).limit(limit).all()
    return {"meetings": meetings, "total": total}
