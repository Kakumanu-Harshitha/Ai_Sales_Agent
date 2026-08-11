from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text, Boolean, Float
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from apps.api.db.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class Company(Base):
    __tablename__ = 'companies'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    domain = Column(String, unique=True, index=True)
    industry = Column(String, nullable=True)
    website = Column(String, nullable=True)
    org_type = Column(String, nullable=True)       # Hospital, Diagnostic Chain, etc.
    state = Column(String, nullable=True)
    city = Column(String, nullable=True)
    employee_size = Column(String, nullable=True)
    country = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    contacts = relationship("Contact", back_populates="company")

class Contact(Base):
    __tablename__ = 'contacts'
    id = Column(Integer, primary_key=True, index=True)
    company_id = Column(Integer, ForeignKey('companies.id'))
    first_name = Column(String)
    last_name = Column(String)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String, nullable=True)
    title = Column(String, nullable=True)
    linkedin_url = Column(String)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    company = relationship("Company", back_populates="contacts")
    leads = relationship("Lead", back_populates="contact")

class Lead(Base):
    __tablename__ = 'leads'
    id = Column(Integer, primary_key=True, index=True)
    contact_id = Column(Integer, ForeignKey('contacts.id'))
    status = Column(String, default="new")  # new, scored, contacted, replied, meeting_booked, proposal_sent, closed_won, closed_lost
    deal_value = Column(Float, nullable=True)
    lead_score = Column(Float, nullable=True)
    priority = Column(String, nullable=True)  # low, medium, high
    source = Column(String, nullable=True)  # Prospecting Agent, Manual, etc.
    campaign_id = Column(Integer, ForeignKey('campaigns.id'), nullable=True)
    stage_entered_at = Column(DateTime, default=utcnow)
    last_activity_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    contact = relationship("Contact", back_populates="leads")
    activities = relationship("Activity", back_populates="lead")
    campaign = relationship("Campaign", back_populates="leads")

class Signal(Base):
    __tablename__ = 'signals'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    
    signal_type = Column(String, nullable=True)
    headline = Column(String, nullable=True)
    description = Column(Text)
    business_impact = Column(Text, nullable=True)
    why_it_matters = Column(Text, nullable=True)
    
    source_name = Column(String, nullable=True)
    source_url = Column(String, nullable=True)
    source_type = Column(String, nullable=True)
    published_date = Column(DateTime, nullable=True)
    
    confidence_score = Column(Float, nullable=True)
    score_contribution = Column(Float, nullable=True)
    priority = Column(String, nullable=True)
    
    recommended_action = Column(String, nullable=True)
    suggested_pitch = Column(Text, nullable=True)
    target_persona = Column(String, nullable=True)
    icp_match = Column(Float, nullable=True)
    
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class LeadScore(Base):
    __tablename__ = 'lead_scores'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    score = Column(Float)
    created_at = Column(DateTime, default=utcnow)

class SignatureTemplate(Base):
    __tablename__ = 'signature_templates'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False) # e.g. "Founder"
    full_name = Column(String, nullable=True)
    designation = Column(String, nullable=True)
    department = Column(String, nullable=True)
    company = Column(String, nullable=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)
    linkedin = Column(String, nullable=True)
    address = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    digital_signature_url = Column(String, nullable=True)
    header_banner_url = Column(String, nullable=True)
    footer_banner_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class Email(Base):
    __tablename__ = 'emails'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    subject = Column(String)
    body = Column(Text)
    html_body = Column(Text, nullable=True)
    header_image_url = Column(String, nullable=True)
    signature_template_id = Column(Integer, ForeignKey('signature_templates.id'), nullable=True)
    outreach_template_id = Column(Integer, ForeignKey('outreach_templates.id'), nullable=True)
    outreach_template_name = Column(String, nullable=True)
    full_name = Column(String, nullable=True)
    designation = Column(String, nullable=True)
    department = Column(String, nullable=True)
    company = Column(String, nullable=True)
    sender_email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    website = Column(String, nullable=True)
    linkedin = Column(String, nullable=True)
    address = Column(String, nullable=True)
    logo_url = Column(String, nullable=True)
    digital_signature_url = Column(String, nullable=True)
    footer_banner_url = Column(String, nullable=True)
    sent_at = Column(DateTime, default=utcnow)
    status = Column(String, default="sent")
    from_email = Column(String)
    to_email = Column(String)
    delivered_at = Column(DateTime, nullable=True)
    opened_at = Column(DateTime, nullable=True)
    clicked_at = Column(DateTime, nullable=True)
    replied_at = Column(DateTime, nullable=True)
    gmail_message_id = Column(String, unique=True, nullable=True)
    error_message = Column(Text, nullable=True)

class LinkedinMessage(Base):
    __tablename__ = 'linkedin_messages'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    message = Column(Text)
    sent_at = Column(DateTime, default=utcnow)

class Call(Base):
    __tablename__ = 'calls'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    call_date = Column(DateTime, default=utcnow)
    duration_minutes = Column(Integer, nullable=True)
    outcome = Column(String, nullable=True)  # connected, voicemail, no_answer, meeting_booked
    notes = Column(Text, nullable=True)
    follow_up_required = Column(Boolean, default=False)
    follow_up_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow)

class Meeting(Base):
    __tablename__ = 'meetings'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    lead_name = Column(String, nullable=True)
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    scheduled_at = Column(DateTime)       # start time
    end_time = Column(DateTime, nullable=True)
    timezone = Column(String, nullable=True, default='UTC')
    google_event_id = Column(String, nullable=True, unique=True)
    meet_link = Column(String, nullable=True)
    organizer_email = Column(String, nullable=True)
    attendee_email = Column(String, nullable=True)
    calendar_status = Column(String, nullable=True, default='confirmed')
    status = Column(String, default='scheduled')
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class Activity(Base):
    __tablename__ = 'activities'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    type = Column(String)  # Lead Created, Email Sent, etc.
    description = Column(Text)
    created_at = Column(DateTime, default=utcnow)
    lead = relationship("Lead", back_populates="activities")

class Note(Base):
    __tablename__ = 'notes'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'))
    content = Column(Text)
    created_at = Column(DateTime, default=utcnow)

class Reply(Base):
    __tablename__ = 'replies'
    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey('leads.id'), nullable=True)
    thread_id = Column(String, nullable=True)
    message_id = Column(String, unique=True)
    gmail_message_id = Column(String, unique=True, nullable=True)
    sender_email = Column(String, nullable=True)
    sender_name = Column(String, nullable=True)
    subject = Column(String, nullable=True)
    content = Column(Text, nullable=True)  # Legacy snippet
    raw_body = Column(Text, nullable=True)
    clean_body = Column(Text, nullable=True)
    received_at = Column(DateTime, default=utcnow)
    created_at = Column(DateTime, default=utcnow)
    processed = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False)
    is_deleted = Column(Boolean, default=False)

    analysis = relationship("ReplyAnalysis", back_populates="reply", uselist=False, cascade="all, delete-orphan")


class ReplyAnalysis(Base):
    __tablename__ = 'reply_analyses'
    id = Column(Integer, primary_key=True, index=True)
    reply_id = Column(Integer, ForeignKey('replies.id'), unique=True)
    intent = Column(String, nullable=True)
    sentiment = Column(String, nullable=True)
    objections = Column(Text, nullable=True) # Stored as JSON string
    summary = Column(Text, nullable=True)
    priority = Column(String, nullable=True)
    recommended_action = Column(String, nullable=True)
    reply_draft = Column(Text, nullable=True)
    analyzed_at = Column(DateTime, default=utcnow)

    reply = relationship("Reply", back_populates="analysis")

class Campaign(Base):
    __tablename__ = 'campaigns'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    status = Column(String)
    created_at = Column(DateTime, default=utcnow)
    leads = relationship("Lead", back_populates="campaign")

class Notification(Base):
    __tablename__ = 'notifications'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'))
    content = Column(Text)
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)

class DashboardMetric(Base):
    __tablename__ = 'dashboard_metrics'
    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String)
    value = Column(Float)
    date = Column(DateTime, default=utcnow)

class AgentSettings(Base):
    __tablename__ = 'agent_settings'
    id = Column(Integer, primary_key=True, index=True)
    enabled = Column(Boolean, default=False)
    interval_minutes = Column(Integer, default=30)
    default_template_id = Column(Integer, nullable=True)
    default_outreach_template_id = Column(Integer, ForeignKey("outreach_templates.id"), nullable=True)
    auto_send_emails = Column(Boolean, default=False)
    max_leads_per_run = Column(Integer, default=10)
    max_outreach_per_cycle = Column(Integer, default=3)   # how many outreach emails to send per agent cycle
    daily_email_limit = Column(Integer, default=50)
    reply_monitoring = Column(Boolean, default=True)
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    current_status = Column(String, default="Idle") # Idle, Running, Paused, Error
    current_stage = Column(String, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class OutreachTemplate(Base):
    __tablename__ = "outreach_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    subject = Column(String)
    body = Column(String)
    category = Column(String, index=True)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)

class JobTemplate(Base):
    __tablename__ = 'job_templates'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    regions = Column(String, nullable=True)
    company_size_min = Column(Integer, nullable=True)
    company_size_max = Column(Integer, nullable=True)
    industries = Column(String) # JSON or comma separated
    target_roles = Column(String) # JSON or comma separated
    keywords = Column(String)
    technologies = Column(String)
    max_results = Column(Integer, default=15)
    created_at = Column(DateTime, default=utcnow)

