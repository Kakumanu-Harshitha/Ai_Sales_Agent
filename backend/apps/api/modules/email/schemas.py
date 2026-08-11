from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

class SendEmailRequest(BaseModel):
    to: EmailStr
    subject: str
    body: str
    from_email: EmailStr
    lead_id: Optional[int] = None

class EmailResponse(BaseModel):
    id: int
    lead_id: Optional[int]
    subject: str
    body: str
    status: str
    from_email: Optional[str]
    to_email: Optional[str]
    sent_at: datetime
    class Config:
        from_attributes = True

class ReplyResponse(BaseModel):
    id: int
    lead_id: Optional[int]
    message_id: str
    content: str
    received_at: datetime
    processed: bool
    class Config:
        from_attributes = True
