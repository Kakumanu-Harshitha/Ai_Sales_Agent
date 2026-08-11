"""
Pipeline module — Pydantic schemas for the pipeline report.
Matches the shared schema contract from SETV_updated_prompts_fastapi.md.
"""

from pydantic import BaseModel
from typing import Optional, List, Dict


class LeadFunnel(BaseModel):
    new: int = 0
    scored: int = 0
    contacted: int = 0
    replied: int = 0
    meeting_booked: int = 0
    proposal_sent: int = 0
    closed_won: int = 0
    closed_lost: int = 0


class PipelineForecast(BaseModel):
    total_value: float = 0.0
    weighted_value: float = 0.0
    close_probability: float = 0.0


class RevenueForecast(BaseModel):
    expected_revenue: float = 0.0
    forecast_period: str = "next_30_days"


class CampaignPerformance(BaseModel):
    sent: int = 0
    opened: int = 0
    clicked: int = 0
    replied: int = 0


class ConversionRate(BaseModel):
    outreach_to_reply: float = 0.0
    reply_to_meeting: float = 0.0
    meeting_to_close: float = 0.0


class PipelineReportResponse(BaseModel):
    lead_funnel: LeadFunnel
    pipeline_forecast: PipelineForecast
    revenue_forecast: RevenueForecast
    risk_flags: List[str]
    stalled_deals: List[str]
    campaign_performance: CampaignPerformance
    conversion_rate: ConversionRate
    next_best_actions: List[str]
