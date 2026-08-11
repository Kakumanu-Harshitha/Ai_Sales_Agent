"""
Prospecting module schemas.

Updated to support the job-based async pipeline. Preserves
backward compatibility with the original discover/save endpoints.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any


# ── Search Request (job-based, full ICP) ──────────────────────────────────────

class ProspectingSearchRequest(BaseModel):
    """Full ICP-based search request that creates an async job."""
    industries: List[str] = Field(default_factory=list, examples=[["Healthcare", "Hospital & Health Care"]])
    keywords: List[str] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list, examples=[["CTO", "CEO", "Director of IT"]])
    regions: List[str] = Field(default_factory=list, examples=[["US", "California"]])
    company_size_min: Optional[int] = None
    company_size_max: Optional[int] = None
    technologies: List[str] = Field(default_factory=list)
    max_results: int = Field(20, ge=1, le=100)


class SearchJobResponse(BaseModel):
    """Returned immediately when a search job is created."""
    job_id: int
    status: str
    message: str
    created_at: Any  # datetime


class JobStatusResponse(BaseModel):
    """Full job status response for polling."""
    job_id: int
    status: str
    created_at: Any
    started_at: Optional[Any] = None
    completed_at: Optional[Any] = None
    total_companies_discovered: int = 0
    total_leads_qualified: int = 0
    total_leads_persisted: int = 0
    error_message: Optional[str] = None
    provider_stats: dict = {}


# ── Legacy simple request (backward compatible) ────────────────────────────────

class ProspectingRequest(BaseModel):
    """Simple legacy request for /prospecting/discover."""
    region: str = "US"
    industry: str = "Healthcare"
    employee_band: Optional[str] = None
    keywords: Optional[List[str]] = None
    org_type: Optional[str] = None
    state: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = "US"
    max_results: int = Field(10, ge=1, le=50)


# ── Response schemas ───────────────────────────────────────────────────────────

class DiscoveredContact(BaseModel):
    name: Optional[str] = None
    designation: Optional[str] = None
    public_business_email: Optional[str] = None
    public_phone_number: Optional[str] = None
    linkedin_profile: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    confidence: Optional[str] = "medium"


class DiscoveredLead(BaseModel):
    company_name: str
    website: Optional[str] = None
    industry: Optional[str] = None
    org_type: Optional[str] = None
    location: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    discovery_timestamp: Optional[str] = None
    contacts: List[DiscoveredContact] = []


class ProspectingResponse(BaseModel):
    leads: List[DiscoveredLead] = []
    grounding_chunks: List[Any] = []
    status: str = "success"
    message: Optional[str] = None


class SaveLeadsRequest(BaseModel):
    leads: List[dict]


class SaveLeadsResponse(BaseModel):
    saved: int
    total_requested: int
    errors: List[str] = []
