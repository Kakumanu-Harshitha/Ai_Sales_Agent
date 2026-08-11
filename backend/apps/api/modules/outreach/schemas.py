"""
Outreach module — schemas for outreach messages.
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class OutreachCreate(BaseModel):
    lead_id: int
    channel: str = "email"  # email | linkedin
    subject: Optional[str] = None
    body: str
    step_number: int = 1


class OutreachResponse(BaseModel):
    id: int
    lead_id: Optional[int] = None
    subject: Optional[str] = None
    body: str
    status: str
    sent_at: Optional[datetime] = None

    class Config:
        from_attributes = True
