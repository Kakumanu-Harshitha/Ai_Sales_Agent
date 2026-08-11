from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class TimeSlot(BaseModel):
    start: datetime
    end: datetime


class BookMeetingRequest(BaseModel):
    account_id: int
    contact_id: int
    lead_id: Optional[int] = None
    contact_email: Optional[str] = None   # Optional — backend resolves from DB if missing
    slot_start: datetime
    slot_end: Optional[datetime] = None   # Optional — defaults to start + 30 min
    timezone: Optional[str] = None
    title: str = 'SETV Discovery Call'
    description: Optional[str] = 'AI-scheduled discovery meeting via SETV Sales Agent'


class BookMeetingResponse(BaseModel):
    status: str
    meeting_id: Optional[int] = None
    meeting_link: Optional[str] = None
    event_id: Optional[str] = None
    lead_id: Optional[int] = None
    lead_name: Optional[str] = None
    attendee_email: Optional[str] = None
    organizer_email: Optional[str] = None
    scheduled_at: Optional[str] = None
    end_time: Optional[str] = None


class MeetingResponse(BaseModel):
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
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class MeetingListResponse(BaseModel):
    meetings: List[MeetingResponse]
    total: int
