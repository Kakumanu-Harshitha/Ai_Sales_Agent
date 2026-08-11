"""
schemas/internal.py - Internal Data Transfer Objects (DTOs).

These are the types that flow between services inside the Prospecting Agent.
They are NOT API-facing models; they live only in memory during a prospecting run.
All DTOs are immutable (frozen=True) to prevent accidental mutation between layers.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enumerations -----------------------------------------------------------


class EnrichmentStatus(str, Enum):
    """Tracks how completely a contact has been enriched."""
    FULL = "full"           # All fields resolved and verified
    PARTIAL = "partial"     # Some fields missing; flagged for manual review
    FAILED = "failed"       # Enrichment attempted but all providers returned nothing


class VerificationStatus(str, Enum):
    """Tracks the outcome of contact verification."""
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    INVALID = "invalid"


class ProviderName(str, Enum):
    """All registered data providers."""
    APOLLO = "apollo"
    TAVILY = "tavily"
    TINYFISH = "tinyfish"
    HEALTHCARE_DIRECTORY = "healthcare_directory"
    NPI_REGISTRY = "npi_registry"
    ABSTRACT = "abstract"
    ABSTRACT_API = "abstract_api"
    PROSPEO = "prospeo"
    HUNTER = "hunter"
    OSINT = "osint"
    OVERPASS = "overpass"
    SERPER = "serper"
    MANUAL = "manual"


# --- ICP Filter -------------------------------------------------------------


class ICPFilter(BaseModel):
    """
    Ideal Customer Profile criteria used to filter and score leads.

    All fields are optional so callers can specify as many or as few as needed.
    Missing fields are treated as 'no constraint' during qualification.
    """

    model_config = {"frozen": True}

    industries: list[str] = Field(
        default_factory=list,
        description="Target industries, e.g. ['Healthcare', 'Hospital & Health Care']",
        examples=[["Healthcare", "Hospital & Health Care", "Medical Devices"]],
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords to search for, e.g. ['EHR', 'digital transformation']",
    )
    target_roles: list[str] = Field(
        default_factory=list,
        description="Decision-maker job titles to target",
        examples=[["CTO", "VP of IT", "Chief Medical Officer", "Director of Digital Health"]],
    )
    regions: list[str] = Field(
        default_factory=list,
        description="Target geographies, e.g. ['US', 'California']",
    )
    company_size_min: int | None = Field(None, ge=1, description="Minimum employee count")
    company_size_max: int | None = Field(None, ge=1, description="Maximum employee count")
    technologies: list[str] = Field(
        default_factory=list,
        description="Technology stack keywords to look for",
    )
    max_results: int = Field(
        50, ge=1, le=500, description="Maximum leads to return from this search"
    )


# --- Candidate (pre-qualification) DTOs -------------------------------------


class CandidateCompany(BaseModel):
    """
    A company returned by a discovery provider before deduplication
    or qualification. Fields are intentionally loose - providers return
    different subsets.
    """

    model_config = {"frozen": True}

    internal_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Ephemeral ID assigned during this run (not a DB ID)",
    )
    name: str
    domain: str | None = None
    website: str | None = None
    industry: str | None = None
    employee_count: int | None = None
    employee_range: str | None = None  # e.g. "51-200"
    hq_city: str | None = None
    hq_state: str | None = None
    hq_country: str | None = None
    description: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    source_provider: ProviderName = ProviderName.MANUAL
    raw_payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Original provider response stored verbatim for audit",
    )


class CandidateContact(BaseModel):
    """
    A person (potential decision maker) returned by a provider,
    before enrichment or verification.
    """

    model_config = {"frozen": True}

    internal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    company_internal_id: str = Field(
        description="References CandidateCompany.internal_id"
    )
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    title: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    source_provider: ProviderName = ProviderName.MANUAL
    source_reliability: int = Field(
        default=50,
        ge=0,
        le=100,
        description=(
            "Provider reliability weight used by ContactCandidatePool ranking. "
            "Defaults: Apollo=90, PDL=75, Tavily+Groq=70, NPI=30. "
            "These are starting defaults - review and tune after observing real output."
        ),
    )
    raw_payload: dict[str, Any] = Field(default_factory=dict)

    # --- Extraction intelligence fields (populated during Tavily+Groq extraction) ---

    extracted_email: str | None = Field(
        default=None,
        description="Literal email address extracted from the source page content. "
                    "Takes precedence over pattern-generated emails in enrichment.",
    )
    extracted_phone: str | None = Field(
        default=None,
        description="Phone number extracted directly from the source page.",
    )
    department: str | None = Field(
        default=None,
        description="Department or division inferred from the source page.",
    )
    location: str | None = Field(
        default=None,
        description="City/state/region extracted from the source page.",
    )
    organization_type: str | None = Field(
        default=None,
        description="Inferred organization type, e.g. 'hospital', 'clinic', 'imaging center'.",
    )
    leadership_indicator: bool = Field(
        default=False,
        description="True if this contact was found on a leadership, board, or executive page.",
    )
    extraction_confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence score (0-1) from the extractor for this contact.",
    )
    source_url: str | None = Field(
        default=None,
        description="URL of the page where this contact was found.",
    )
    selection_reason: str | None = Field(
        default=None,
        description="Human-readable explanation of why this contact was selected by the pool.",
    )

    @property
    def display_name(self) -> str:
        if self.full_name:
            return self.full_name
        parts = [p for p in [self.first_name, self.last_name] if p]
        return " ".join(parts) if parts else "Unknown"


# --- Contact Pool Ranking ---------------------------------------------------


class ContactScore(BaseModel):
    """
    Composite ranking score for a single contact candidate.
    Used by ContactCandidatePool to select the best candidate before enrichment.
    All component scores are 0-100; composite is a weighted sum clamped to 0-100.
    """

    model_config = {"frozen": True}

    seniority: int = Field(0, ge=0, le=100, description="CxO=100, VP/Dir=80, Mgr=60, Admin=30, unknown=0")
    role_relevance: int = Field(0, ge=0, le=100, description="Overlap with ICP target_roles")
    source_reliability: int = Field(50, ge=0, le=100, description="Per-provider default (adjustable)")
    email_available: int = Field(0, ge=0, le=50, description="Email already known: +15")
    email_verified: int = Field(0, ge=0, le=50, description="Email pre-verified by provider: +10")
    composite: int = Field(0, ge=0, le=100, description="Weighted composite used for selection")


# --- Enrichment / Research DTOs ---------------------------------------------


class EnrichedContact(BaseModel):
    """Contact after enrichment - some fields may still be None if providers had no data."""

    model_config = {"frozen": True}

    source_contact: CandidateContact
    email: str | None = None
    email_verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    phone: str | None = None
    phone_verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    linkedin_url: str | None = None
    twitter_url: str | None = None
    enrichment_status: EnrichmentStatus = EnrichmentStatus.PARTIAL
    enrichment_providers_used: list[ProviderName] = Field(default_factory=list)


class CompanyContext(BaseModel):
    """
    Structured company context synthesized by the LLM from public web data.
    Used to enrich lead records and improve qualification reasoning.
    """

    model_config = {"frozen": True}

    summary: str | None = None
    tech_focus: list[str] = Field(
        default_factory=list,
        description="Technologies or platforms the company uses or sells",
    )
    digital_transformation_signals: list[str] = Field(
        default_factory=list,
        description="Indicators of digital transformation interest",
    )
    decision_makers_mentioned: list[str] = Field(
        default_factory=list,
        description="Names of executives/leaders found on the page",
    )
    scraped_emails: list[str] = Field(
        default_factory=list,
        description="Generic emails extracted from the website text",
    )
    estimated_size: str | None = None
    key_products_services: list[str] = Field(default_factory=list)
    research_source_url: str | None = None
    llm_model_used: str | None = None


# --- Qualification ----------------------------------------------------------


class QualificationResult(BaseModel):
    """Outcome of the LeadQualificationService for a single company."""

    model_config = {"frozen": True}

    qualified: bool
    needs_contact_research: bool = Field(
        default=False,
        description=(
            "True when score >= threshold but contact_actionability == 0. "
            "Lead is persisted as 'qualified_needs_contact_research' rather "
            "than 'new' - visible in CRM but separated from actionable leads."
        ),
    )
    score: int = Field(ge=0, le=100)
    contact_actionability: int = Field(
        default=0,
        ge=0,
        le=15,
        description="Hard-gate dimension score. Must be > 0 for full qualification.",
    )
    score_breakdown: dict[str, int] = Field(
        default_factory=dict,
        description="Per-dimension scores, e.g. {'industry': 30, 'size': 20, 'role': 20, 'contact_actionability': 15}",
    )
    rationale: str | None = Field(
        None,
        description="LLM-generated natural language explanation (None if LLM unavailable)",
    )
    disqualification_reasons: list[str] = Field(default_factory=list)


# --- Confidence Scoring -----------------------------------------------------


class LeadConfidenceScore(BaseModel):
    """
    Separate from the ICP qualification score.
    Tracks how confident we are in the quality of each pipeline output component.
    Stored alongside the lead for CRM display and downstream prioritisation.
    """

    model_config = {"frozen": True}

    icp_score: int = Field(ge=0, le=100, description="ICP qualification score (0-100)")
    contact_dm_confidence: int = Field(
        ge=0,
        le=100,
        description="Decision-maker confidence: seniority + source_reliability composite",
    )
    email_confidence: int = Field(
        ge=0,
        le=100,
        description="Email confidence: verified=100, unverified provider=60, pattern=30, none=0",
    )
    overall: int = Field(
        ge=0,
        le=100,
        description="Weighted composite: icp*0.5 + dm*0.3 + email*0.2",
    )


# --- Final Qualified Lead ---------------------------------------------------


class QualifiedLead(BaseModel):
    """
    A fully-processed lead ready to be persisted by ProspectRepository.

    This is the final output of the orchestrator pipeline for a single
    company + contact pair. One QualifiedLead is created per contact
    within a qualified company.
    """

    model_config = {"frozen": True}

    company: CandidateCompany
    contact: EnrichedContact
    company_context: CompanyContext | None = None
    qualification: QualificationResult
    confidence: LeadConfidenceScore | None = None
    source_providers: list[ProviderName] = Field(default_factory=list)
