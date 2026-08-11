"""
Replies module — Pydantic schemas for reply classification.
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class ReplyClassificationResponse(BaseModel):
    intent: str  # Interested | Pricing Request | Demo Request | Meeting Request | Not Interested | Wrong Person | Out of Office
    sentiment: str  # positive | neutral | negative
    objections: List[str] = []
    summary: str = ""
    next_action: str = ""
    draft_reply: str = ""


class ReplyResponse(BaseModel):
    id: int
    lead_id: Optional[int] = None
    message_id: Optional[str] = None
    content: Optional[str] = None
    classification: Optional[ReplyClassificationResponse] = None
    processed: bool = False

    class Config:
        from_attributes = True
