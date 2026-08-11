"""
Company Intelligence API — Schemas.
"""
from pydantic import BaseModel
from typing import Optional, Any
from datetime import datetime


class WebsiteInsightOut(BaseModel):
    id: int
    page_type: str
    page_url: Optional[str] = None
    page_title: Optional[str] = None
    raw_text: Optional[str] = None
    scraped_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LinkedinInsightOut(BaseModel):
    id: int
    post_type: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    source_url: Optional[str] = None
    published_date: Optional[datetime] = None
    is_hiring: bool = False
    is_expansion: bool = False
    is_ai_initiative: bool = False
    is_healthcare_initiative: bool = False
    is_partnership: bool = False
    is_award: bool = False
    scraped_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class NewsInsightOut(BaseModel):
    id: int
    event_type: Optional[str] = None
    headline: Optional[str] = None
    summary: Optional[str] = None
    source_name: Optional[str] = None
    source_url: Optional[str] = None
    published_date: Optional[datetime] = None
    relevance_score: Optional[float] = None
    scraped_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AICompanySummaryOut(BaseModel):
    id: int
    company_overview: Optional[str] = None
    business_model: Optional[str] = None
    industry: Optional[str] = None
    core_products_services: Optional[str] = None
    current_priorities: Optional[str] = None
    business_goals: Optional[str] = None
    technology_focus: Optional[str] = None
    healthcare_focus: Optional[str] = None
    ai_initiatives: Optional[str] = None
    digital_transformation: Optional[str] = None
    innovation_areas: Optional[str] = None
    recent_initiatives: Optional[str] = None
    expansion_plans: Optional[str] = None
    global_presence: Optional[str] = None
    research_programs: Optional[str] = None
    hiring_activity: Optional[str] = None
    potential_challenges: Optional[str] = None
    possible_opportunities: Optional[str] = None
    buying_signals_detected: Optional[str] = None
    intelligence_completeness: Optional[float] = None
    generated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CompanyIntelligenceOut(BaseModel):
    id: int
    company_id: int
    status: str
    last_refreshed_at: Optional[datetime] = None
    next_refresh_at: Optional[datetime] = None
    company_website: Optional[str] = None
    linkedin_url: Optional[str] = None
    website_insights: list[WebsiteInsightOut] = []
    linkedin_insights: list[LinkedinInsightOut] = []
    news_insights: list[NewsInsightOut] = []
    ai_summary: Optional[AICompanySummaryOut] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
