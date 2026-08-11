import logging
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from apps.api.db.database import get_db
from .schemas import (
    CompanyCreate, CompanyResponse,
    ContactCreate, ContactResponse,
    LeadCreate, LeadResponse, LeadListResponse, LeadTimelineResponse,
    CampaignListResponse,
    CallCreate, CallResponse,
    NoteCreate, NoteResponse,
    LeadFullDetailResponse, SignalResponse, ActivityResponse,
)
from .models import (
    Call, Note, Signal, Activity, Email, Company, Contact, Meeting, Lead, Reply,
)
from .service import CRMService

router = APIRouter(prefix="/crm", tags=["CRM"])
service = CRMService()
logger = logging.getLogger(__name__)


@router.post("/companies/upsert", response_model=CompanyResponse)
def upsert_company(company: CompanyCreate, db: Session = Depends(get_db)):
    return service.upsert_company(db, company)


@router.post("/contacts/upsert", response_model=ContactResponse)
def upsert_contact(contact: ContactCreate, db: Session = Depends(get_db)):
    return service.upsert_contact(db, contact)


@router.post("/leads", response_model=LeadResponse)
def create_lead(lead: LeadCreate, db: Session = Depends(get_db)):
    return service.create_lead(db, lead)


@router.get("/leads/{lead_id}", response_model=LeadResponse)
def get_lead(lead_id: int, db: Session = Depends(get_db)):
    return service.get_lead(db, lead_id)


@router.get("/leads/{lead_id}/timeline", response_model=LeadTimelineResponse)
def get_lead_timeline(lead_id: int, db: Session = Depends(get_db)):
    return service.get_lead_timeline(db, lead_id)


@router.get("/leads/{lead_id}/full-detail", response_model=LeadFullDetailResponse)
def get_lead_full_detail(lead_id: int, db: Session = Depends(get_db)):
    """Get complete lead detail with all related data. Never returns 500 for empty sections."""
    logger.info(f"[CRM DETAIL] Request for lead_id={lead_id}")

    # Lead — required
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        logger.warning(f"[CRM DETAIL] Lead #{lead_id} not found")
        raise HTTPException(status_code=404, detail=f"Lead #{lead_id} not found")
    logger.info(f"[CRM DETAIL] Lead #{lead_id} found, status={lead.status}")

    # Contact & Company — optional
    contact = None
    company = None
    try:
        contact = db.query(Contact).filter(Contact.id == lead.contact_id).first() if lead.contact_id else None
        company = db.query(Company).filter(Company.id == contact.company_id).first() if contact and contact.company_id else None
        logger.info(f"[CRM DETAIL] contact={contact.email if contact else None}, company={company.name if company else None}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching contact/company: {e}")

    # Signals
    signals = []
    try:
        signals = db.query(Signal).filter(Signal.lead_id == lead_id).order_by(Signal.created_at.desc()).all()
        logger.info(f"[CRM DETAIL] signals={len(signals)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching signals: {e}")

    # Emails
    emails = []
    try:
        emails = db.query(Email).filter(Email.lead_id == lead_id).order_by(Email.sent_at.desc()).all()
        logger.info(f"[CRM DETAIL] emails={len(emails)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching emails: {e}")

    # Calls
    calls = []
    try:
        calls = db.query(Call).filter(Call.lead_id == lead_id).order_by(Call.call_date.desc()).all()
        logger.info(f"[CRM DETAIL] calls={len(calls)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching calls: {e}")

    # Activities
    activities = []
    try:
        activities = db.query(Activity).filter(Activity.lead_id == lead_id).order_by(Activity.created_at.desc()).all()
        logger.info(f"[CRM DETAIL] activities={len(activities)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching activities: {e}")

    # Notes
    notes = []
    try:
        notes = db.query(Note).filter(Note.lead_id == lead_id).order_by(Note.created_at.desc()).all()
        logger.info(f"[CRM DETAIL] notes={len(notes)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching notes: {e}")

    # Meetings
    meetings = []
    try:
        meetings = db.query(Meeting).filter(Meeting.lead_id == lead_id).order_by(Meeting.scheduled_at.desc()).all()
        logger.info(f"[CRM DETAIL] meetings={len(meetings)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching meetings: {e}")

    # Replies
    replies = []
    try:
        replies = db.query(Reply).filter(Reply.lead_id == lead_id).order_by(Reply.received_at.desc()).all()
        logger.info(f"[CRM DETAIL] replies={len(replies)}")
    except Exception as e:
        logger.error(f"[CRM DETAIL] Error fetching replies: {e}")

    logger.info(f"[CRM DETAIL] Sending response for lead #{lead_id}")
    return {
        'lead': lead, 'company': company, 'contact': contact,
        'signals': signals, 'emails': emails, 'calls': calls,
        'activities': activities, 'notes': notes, 'meetings': meetings,
        'replies': replies,
    }


# ── Top-level list routes (also exposed at /leads and /campaigns via main.py aliases) ---

@router.get("/leads", response_model=LeadListResponse)
def list_leads(
    status: str | None = Query(None, description="Filter by lead status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return service.list_leads(db, status=status, skip=skip, limit=limit)


@router.get("/campaigns", response_model=CampaignListResponse)
def list_campaigns(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    return service.list_campaigns(db, skip=skip, limit=limit)


# ── Call routes ───────────────────────────────────────────────────────────────

@router.post("/calls", response_model=CallResponse)
def log_call(call: CallCreate, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    new_call = Call(
        lead_id=call.lead_id,
        call_date=call.call_date or datetime.now(timezone.utc),
        duration_minutes=call.duration_minutes,
        outcome=call.outcome,
        notes=call.notes,
        follow_up_required=call.follow_up_required,
        follow_up_date=call.follow_up_date,
    )
    db.add(new_call)
    # Log activity
    lead = db.query(Lead).filter(Lead.id == call.lead_id).first()
    if lead:
        lead.last_activity_at = datetime.now(timezone.utc)
        activity = Activity(
            lead_id=call.lead_id,
            type='Call Logged',
            description=(
                f'Call logged. Outcome: {call.outcome}. '
                f'Duration: {call.duration_minutes} min. Notes: {call.notes}'
            ),
        )
        db.add(activity)
    db.commit()
    db.refresh(new_call)
    return new_call


@router.get("/calls/{lead_id}", response_model=list[CallResponse])
def get_calls_for_lead(lead_id: int, db: Session = Depends(get_db)):
    return db.query(Call).filter(Call.lead_id == lead_id).order_by(Call.call_date.desc()).all()


# ── Note routes ───────────────────────────────────────────────────────────────

@router.post("/notes", response_model=NoteResponse)
def add_note(note: NoteCreate, db: Session = Depends(get_db)):
    from datetime import datetime, timezone
    new_note = Note(lead_id=note.lead_id, content=note.content)
    db.add(new_note)
    lead = db.query(Lead).filter(Lead.id == note.lead_id).first()
    if lead:
        lead.last_activity_at = datetime.now(timezone.utc)
        activity = Activity(
            lead_id=note.lead_id,
            type='Note Added',
            description=note.content[:200],
        )
        db.add(activity)
    db.commit()
    db.refresh(new_note)
    return new_note


# ── Activity routes ───────────────────────────────────────────────────────────

@router.get("/activities/{lead_id}", response_model=list[ActivityResponse])
def get_activities(lead_id: int, db: Session = Depends(get_db)):
    return db.query(Activity).filter(Activity.lead_id == lead_id).order_by(Activity.created_at.desc()).all()


# ── Signal routes ─────────────────────────────────────────────────────────────

@router.get("/signals/{lead_id}", response_model=list[SignalResponse])
def get_signals_for_lead(lead_id: int, db: Session = Depends(get_db)):
    return db.query(Signal).filter(Signal.lead_id == lead_id).order_by(Signal.created_at.desc()).all()


# ── Email routes ──────────────────────────────────────────────────────────────

@router.get("/leads/{lead_id}/emails", response_model=list)
def get_emails_for_lead(lead_id: int, db: Session = Depends(get_db)):
    return db.query(Email).filter(Email.lead_id == lead_id).order_by(Email.sent_at.desc()).all()


# ── Lead status / deal-value update ──────────────────────────────────────────

class LeadStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


@router.patch("/leads/{lead_id}/status")
def update_lead_status(lead_id: int, payload: LeadStatusUpdate, db: Session = Depends(get_db)):
    """Manually update a lead's pipeline status and log it as an Activity."""
    from datetime import datetime, timezone
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead #{lead_id} not found")
    old_status = lead.status
    lead.status = payload.status
    lead.last_activity_at = datetime.now(timezone.utc)
    activity = Activity(
        lead_id=lead_id,
        type='Status Changed',
        description=f'Status updated from "{old_status}" to "{payload.status}"'
        + (f'. Notes: {payload.notes}' if payload.notes else ''),
    )
    db.add(activity)
    db.commit()
    db.refresh(lead)
    return {'id': lead.id, 'status': lead.status, 'old_status': old_status}


class LeadDealValueUpdate(BaseModel):
    deal_value: float | None = None


@router.patch("/leads/{lead_id}/deal-value")
def update_lead_deal_value(lead_id: int, payload: LeadDealValueUpdate, db: Session = Depends(get_db)):
    """Update the deal value for a lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail=f"Lead #{lead_id} not found")
    lead.deal_value = payload.deal_value
    db.commit()
    return {'id': lead.id, 'deal_value': lead.deal_value}
