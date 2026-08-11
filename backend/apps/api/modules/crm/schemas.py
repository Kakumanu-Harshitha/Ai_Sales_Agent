from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class CompanyCreate(BaseModel):
    name: str
    domain: str


class CompanyResponse(CompanyCreate):
    id: int
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


class ContactCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    linkedin_url: Optional[str] = None
    company_domain: Optional[str] = None


class ContactResponse(BaseModel):
    id: int
    company_id: Optional[int]
    first_name: str
    last_name: str
    email: str
    linkedin_url: Optional[str]
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


class LeadCreate(BaseModel):
    contact_email: EmailStr
    status: Optional[str] = "new"


class LeadResponse(BaseModel):
    id: int
    contact_id: Optional[int] = None
    status: str
    deal_value: Optional[float] = None
    lead_score: Optional[float] = None
    priority: Optional[str] = None
    campaign_id: Optional[int] = None
    stage_entered_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    class Config:
        from_attributes = True


class LeadListResponse(BaseModel):
    leads: List[LeadResponse]
    total: int


class ActivityResponse(BaseModel):
    id: int
    lead_id: int
    type: str
    description: Optional[str]
    created_at: Optional[datetime]
    class Config:
        from_attributes = True


class LeadTimelineResponse(BaseModel):
    lead: LeadResponse
    activities: List[ActivityResponse]


class CampaignResponse(BaseModel):
    id: int
    name: Optional[str] = None
    status: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True


class CampaignListResponse(BaseModel):
    campaigns: List[CampaignResponse]
    total: int


# ── Call schemas ─────────────────────────────────────────────────────────────

class CallCreate(BaseModel):
    lead_id: int
    call_date: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None
    follow_up_required: bool = False
    follow_up_date: Optional[datetime] = None


class CallResponse(BaseModel):
    id: int
    lead_id: int
    call_date: Optional[datetime]
    duration_minutes: Optional[int]
    outcome: Optional[str]
    notes: Optional[str]
    follow_up_required: bool
    follow_up_date: Optional[datetime]
    created_at: Optional[datetime]
    class Config:
        from_attributes = True


# ── Note schemas ─────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    lead_id: int
    content: str


class NoteResponse(BaseModel):
    id: int
    lead_id: int
    content: str
    created_at: Optional[datetime]
    class Config:
        from_attributes = True


# ── Signal schema ─────────────────────────────────────────────────────────────

class SignalResponse(BaseModel):
    id: int
    lead_id: int
    signal_type: Optional[str] = None
    headline: Optional[str] = None
    description: Optional[str] = None
    business_impact: Optional[str] = None
    why_it_matters: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    published_date: Optional[datetime] = None
    confidence_score: Optional[float] = None
    score_contribution: Optional[float] = None
    priority: Optional[str] = None
    recommended_action: Optional[str] = None
    suggested_pitch: Optional[str] = None
    target_persona: Optional[str] = None
    icp_match: Optional[float] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ── Email detail schema ───────────────────────────────────────────────────────

class EmailDetailResponse(BaseModel):
    id: int
    lead_id: int
    subject: Optional[str]
    body: Optional[str]
    status: Optional[str]
    from_email: Optional[str]
    to_email: Optional[str]
    sent_at: Optional[datetime]
    opened_at: Optional[datetime]
    replied_at: Optional[datetime]
    gmail_message_id: Optional[str] = None
    error_message: Optional[str] = None
    class Config:
        from_attributes = True


# ── Contact detail schema ─────────────────────────────────────────────────────

class ContactDetailResponse(BaseModel):
    id: int
    company_id: Optional[int]
    first_name: Optional[str]
    last_name: Optional[str]
    email: str
    phone: Optional[str]
    title: Optional[str]
    linkedin_url: Optional[str]
    class Config:
        from_attributes = True


# ── Company detail schema ─────────────────────────────────────────────────────

class CompanyDetailResponse(BaseModel):
    id: int
    name: str
    domain: Optional[str]
    industry: Optional[str]
    website: Optional[str]
    org_type: Optional[str]
    state: Optional[str]
    city: Optional[str]
    country: Optional[str]
    employee_size: Optional[str]
    class Config:
        from_attributes = True


# ── Reply schema ──────────────────────────────────────────────────

class ReplyResponse(BaseModel):
    id: int
    lead_id: Optional[int] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    subject: Optional[str] = None
    content: Optional[str] = None
    clean_body: Optional[str] = None
    received_at: Optional[datetime] = None
    processed: Optional[bool] = None
    is_archived: Optional[bool] = None
    class Config:
        from_attributes = True


# ── Meeting detail schema ────────────────────────────────────────────

class MeetingDetailResponse(BaseModel):
    id: int
    lead_id: Optional[int] = None
    lead_name: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    end_time: Optional[datetime] = None
    timezone: Optional[str] = None
    google_event_id: Optional[str] = None
    meet_link: Optional[str] = None
    organizer_email: Optional[str] = None
    attendee_email: Optional[str] = None
    calendar_status: Optional[str] = None
    status: Optional[str] = None
    created_at: Optional[datetime] = None
    class Config:
        from_attributes = True


# ── Full lead detail schema ────────────────────────────────────────────

class LeadFullDetailResponse(BaseModel):
    lead: LeadResponse
    company: Optional[CompanyDetailResponse] = None
    contact: Optional[ContactDetailResponse] = None
    signals: List[SignalResponse] = []
    emails: List[EmailDetailResponse] = []
    calls: List[CallResponse] = []
    activities: List[ActivityResponse] = []
    notes: List[NoteResponse] = []
    meetings: List[MeetingDetailResponse] = []
    replies: List[ReplyResponse] = []
    class Config:
        from_attributes = True
