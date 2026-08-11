"""
Signals module — schemas for signal detection results.
"""

from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class SignalCreate(BaseModel):
    lead_id: int
    signal_type: Optional[str] = None
    headline: Optional[str] = None
    description: str
    business_impact: Optional[str] = None
    why_it_matters: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    published_date: Optional[datetime] = None
    confidence_score: Optional[float] = 0.0
    score_contribution: Optional[float] = 0.0
    priority: Optional[str] = None
    recommended_action: Optional[str] = None
    suggested_pitch: Optional[str] = None
    target_persona: Optional[str] = None
    icp_match: Optional[float] = None

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
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeadScoreResponse(BaseModel):
    id: int
    lead_id: int
    score: float
    created_at: datetime

    class Config:
        from_attributes = True


class SignalReportResponse(BaseModel):
    lead_id: int
    signals: List[SignalResponse]
    lead_score: Optional[float] = None
    priority: Optional[str] = None
