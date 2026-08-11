"""
Intelligence module — Company Intelligence Engine Database Models.

Tables:
  company_intelligence   - Parent record per company (1-to-1 with CRM Company)
  website_insights       - Individual scraped pages (About, Products, etc.)
  linkedin_insights      - Public LinkedIn activity summaries
  news_insights          - Public news events (funding, partnerships, etc.)
  ai_company_summaries   - AI-generated structured Company Intelligence Summaries
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from apps.api.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class CompanyIntelligence(Base):
    """
    Parent intelligence record — one per company.
    Links to the CRM Company table and holds refresh metadata.
    """
    __tablename__ = "company_intelligence"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    company_id = Column(Integer, ForeignKey("companies.id"), unique=True, nullable=False, index=True)

    # Enrichment status
    status = Column(String, default="pending")  # pending, running, completed, partial, failed
    last_refreshed_at = Column(DateTime, nullable=True)
    next_refresh_at = Column(DateTime, nullable=True)
    refresh_interval_days = Column(Integer, default=7)

    # Metadata
    company_website = Column(String, nullable=True)
    linkedin_url = Column(String, nullable=True)
    error_log = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

    # Relationships
    website_insights = relationship("WebsiteInsight", back_populates="intelligence", cascade="all, delete-orphan")
    linkedin_insights = relationship("LinkedinInsight", back_populates="intelligence", cascade="all, delete-orphan")
    news_insights = relationship("NewsInsight", back_populates="intelligence", cascade="all, delete-orphan")
    ai_summaries = relationship("AICompanySummary", back_populates="intelligence", cascade="all, delete-orphan")


class WebsiteInsight(Base):
    """
    Stores extracted text and metadata from a single crawled website page.
    Historical records are preserved — never overwritten.
    """
    __tablename__ = "website_insights"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    intelligence_id = Column(Integer, ForeignKey("company_intelligence.id"), nullable=False, index=True)

    page_type = Column(String, nullable=False)     # homepage, about, products, solutions, blog, careers, etc.
    page_url = Column(String, nullable=True)
    page_title = Column(String, nullable=True)
    raw_text = Column(Text, nullable=True)          # Cleaned plain text extracted from the page

    # Extracted structured fields
    company_overview = Column(Text, nullable=True)
    mission = Column(Text, nullable=True)
    vision = Column(Text, nullable=True)
    core_products = Column(Text, nullable=True)     # JSON list as string
    industries_served = Column(Text, nullable=True) # JSON list as string
    target_customers = Column(Text, nullable=True)
    technology_stack = Column(Text, nullable=True)  # JSON list as string
    awards_certifications = Column(Text, nullable=True)
    partnerships = Column(Text, nullable=True)
    recent_announcements = Column(Text, nullable=True)
    hiring_roles = Column(Text, nullable=True)      # Extracted from Careers page
    leadership_team = Column(Text, nullable=True)   # Extracted from Leadership page

    scraped_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)

    intelligence = relationship("CompanyIntelligence", back_populates="website_insights")


class LinkedinInsight(Base):
    """
    Stores publicly available LinkedIn company activity.
    Sourced via search APIs (not direct scraping) to avoid blocks.
    """
    __tablename__ = "linkedin_insights"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    intelligence_id = Column(Integer, ForeignKey("company_intelligence.id"), nullable=False, index=True)

    post_type = Column(String, nullable=True)      # announcement, hiring, award, partnership, event
    headline = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    source_url = Column(String, nullable=True)
    published_date = Column(DateTime, nullable=True)
    raw_text = Column(Text, nullable=True)

    # Structured intelligence derived from the post
    is_hiring = Column(Boolean, default=False)
    is_expansion = Column(Boolean, default=False)
    is_ai_initiative = Column(Boolean, default=False)
    is_healthcare_initiative = Column(Boolean, default=False)
    is_partnership = Column(Boolean, default=False)
    is_award = Column(Boolean, default=False)

    scraped_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)

    intelligence = relationship("CompanyIntelligence", back_populates="linkedin_insights")


class NewsInsight(Base):
    """
    Stores recent public news events about the company.
    """
    __tablename__ = "news_insights"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    intelligence_id = Column(Integer, ForeignKey("company_intelligence.id"), nullable=False, index=True)

    event_type = Column(String, nullable=True)     # funding, acquisition, expansion, product_launch, partnership, research
    headline = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    source_name = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    published_date = Column(DateTime, nullable=True)
    relevance_score = Column(Float, nullable=True)  # 0-100

    scraped_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)

    intelligence = relationship("CompanyIntelligence", back_populates="news_insights")


class AICompanySummary(Base):
    """
    AI-generated structured Company Intelligence Summary.
    A new record is created on each intelligence refresh — history is preserved.
    """
    __tablename__ = "ai_company_summaries"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    intelligence_id = Column(Integer, ForeignKey("company_intelligence.id"), nullable=False, index=True)
    is_latest = Column(Boolean, default=True)

    # Core Intelligence Fields
    company_overview = Column(Text, nullable=True)
    business_model = Column(Text, nullable=True)
    industry = Column(String, nullable=True)
    core_products_services = Column(Text, nullable=True)   # JSON list as string
    current_priorities = Column(Text, nullable=True)
    business_goals = Column(Text, nullable=True)

    # Technology & Focus Areas
    technology_focus = Column(Text, nullable=True)
    healthcare_focus = Column(Text, nullable=True)
    ai_initiatives = Column(Text, nullable=True)
    digital_transformation = Column(Text, nullable=True)
    innovation_areas = Column(Text, nullable=True)

    # Growth & Activity
    recent_initiatives = Column(Text, nullable=True)
    expansion_plans = Column(Text, nullable=True)
    global_presence = Column(Text, nullable=True)
    research_programs = Column(Text, nullable=True)
    hiring_activity = Column(Text, nullable=True)

    # Sales Intelligence
    potential_challenges = Column(Text, nullable=True)
    possible_opportunities = Column(Text, nullable=True)
    buying_signals_detected = Column(Text, nullable=True)  # JSON list as string

    # Scoring
    intelligence_completeness = Column(Float, nullable=True)  # 0-100, how complete the profile is

    generated_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)

    intelligence = relationship("CompanyIntelligence", back_populates="ai_summaries")
