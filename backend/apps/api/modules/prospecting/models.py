"""
Prospecting module models.

Adds a ProspectingJob table to track async search jobs -
mirroring the standalone agent job system in the main app DB.
"""

from sqlalchemy import Column, Integer, String, DateTime, Text
from datetime import datetime, timezone
from apps.api.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class ProspectingJob(Base):
    """Tracks an async prospecting search job and auto agent workflow execution."""
    __tablename__ = "prospecting_jobs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    status = Column(String, default="pending")  # pending, running, completed, failed
    icp_json = Column(Text, nullable=True)       # Serialized ICP filter for reference
    template_used_id = Column(Integer, nullable=True)
    
    # Metrics
    total_companies_discovered = Column(Integer, default=0)
    total_leads_qualified = Column(Integer, default=0)
    total_leads_persisted = Column(Integer, default=0)
    outreach_generated = Column(Integer, default=0)
    emails_sent = Column(Integer, default=0)
    
    provider_stats_json = Column(Text, nullable=True)  # JSON string of per-provider stats
    error_message = Column(Text, nullable=True)
    execution_logs = Column(Text, nullable=True) # Stored as JSON string list
    discovered_companies_json = Column(Text, nullable=True) # JSON list of companies discovered
    
    
    created_at = Column(DateTime, default=utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
