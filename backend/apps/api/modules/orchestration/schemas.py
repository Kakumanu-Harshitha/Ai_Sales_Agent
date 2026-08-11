"""
Orchestration module — Pydantic schemas.
"""

from pydantic import BaseModel
from typing import Optional, List


class RunProspectingRequest(BaseModel):
    region: str
    industry: str
    employee_band: Optional[str] = None
    keywords: Optional[List[str]] = None
    score_threshold: float = 40.0  # Min score to trigger outreach


class RunProspectingResponse(BaseModel):
    status: str
    leads_discovered: int = 0
    leads_scored: int = 0
    outreach_sent: int = 0
    details: List[dict] = []


class ProcessRepliesRequest(BaseModel):
    max_replies: int = 50


class ProcessRepliesResponse(BaseModel):
    status: str
    replies_processed: int = 0
    meetings_booked: int = 0
    leads_updated: int = 0
    details: List[dict] = []
