"""
Session 3.4 — E2E Verification Script

Seeds the database with sample data and verifies all routes work.
Run with: python -m apps.api.seed.e2e_verify
"""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))

from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

from apps.api.db.database import SessionLocal, engine, Base
from apps.api.core.idempotency import IdempotencyRecord
from apps.api.modules.crm.models import (
    User, Company, Contact, Lead, Signal, LeadScore,
    Email, Activity, Meeting, Campaign, Reply,
)


def seed_data(db: Session):
    """Seed the database with sample data for E2E testing."""
    print("🌱 Seeding database...")

    # Companies
    companies = [
        Company(name="Apollo Hospitals", domain="apollohospitals.com", industry="Healthcare", website="https://apollohospitals.com"),
        Company(name="Practo Technologies", domain="practo.com", industry="HealthTech", website="https://practo.com"),
        Company(name="PharmEasy", domain="pharmeasy.in", industry="Pharma", website="https://pharmeasy.in"),
        Company(name="Narayana Health", domain="narayanahealth.org", industry="Healthcare", website="https://narayanahealth.org"),
        Company(name="MedLife", domain="medlife.com", industry="HealthTech", website="https://medlife.com"),
    ]
    for c in companies:
        existing = db.query(Company).filter(Company.domain == c.domain).first()
        if not existing:
            db.add(c)
    db.flush()

    companies = db.query(Company).all()

    # Contacts
    contacts_data = [
        {"company_idx": 0, "first_name": "Rajesh", "last_name": "Kumar", "email": "rajesh@apollohospitals.com", "title": "CTO"},
        {"company_idx": 0, "first_name": "Priya", "last_name": "Sharma", "email": "priya.sharma@apollohospitals.com", "title": "VP Engineering"},
        {"company_idx": 1, "first_name": "Shashank", "last_name": "ND", "email": "shashank@practo.com", "title": "CEO"},
        {"company_idx": 2, "first_name": "Dharmil", "last_name": "Sheth", "email": "dharmil@pharmeasy.in", "title": "CEO"},
        {"company_idx": 3, "first_name": "Devi", "last_name": "Shetty", "email": "devi@narayanahealth.org", "title": "Chairman"},
        {"company_idx": 4, "first_name": "Atul", "last_name": "Sharma", "email": "atul@medlife.com", "title": "COO"},
    ]
    for cd in contacts_data:
        existing = db.query(Contact).filter(Contact.email == cd["email"]).first()
        if not existing:
            contact = Contact(
                company_id=companies[cd["company_idx"]].id,
                first_name=cd["first_name"],
                last_name=cd["last_name"],
                email=cd["email"],
                title=cd["title"],
            )
            db.add(contact)
    db.flush()

    contacts = db.query(Contact).all()

    # Campaign
    campaign = db.query(Campaign).filter(Campaign.name == "India Healthcare Q3").first()
    if not campaign:
        campaign = Campaign(name="India Healthcare Q3", status="active")
        db.add(campaign)
        db.flush()

    # Leads at various stages
    leads_data = [
        {"contact_idx": 0, "status": "contacted", "deal_value": 75000, "lead_score": 82, "priority": "high", "days_ago": 3},
        {"contact_idx": 1, "status": "replied", "deal_value": 50000, "lead_score": 68, "priority": "medium", "days_ago": 1},
        {"contact_idx": 2, "status": "meeting_booked", "deal_value": 120000, "lead_score": 91, "priority": "high", "days_ago": 0},
        {"contact_idx": 3, "status": "proposal_sent", "deal_value": 200000, "lead_score": 75, "priority": "high", "days_ago": 18},  # stalled
        {"contact_idx": 4, "status": "scored", "deal_value": 30000, "lead_score": 45, "priority": "medium", "days_ago": 12},  # at risk
        {"contact_idx": 5, "status": "closed_won", "deal_value": 95000, "lead_score": 95, "priority": "high", "days_ago": 5},
    ]

    created_leads = []
    for ld in leads_data:
        now = datetime.now(timezone.utc)
        activity_time = now - timedelta(days=ld["days_ago"])
        lead = Lead(
            contact_id=contacts[ld["contact_idx"]].id,
            status=ld["status"],
            deal_value=ld["deal_value"],
            lead_score=ld["lead_score"],
            priority=ld["priority"],
            campaign_id=campaign.id,
            source="Prospecting Agent",
            stage_entered_at=activity_time,
            last_activity_at=activity_time,
        )
        db.add(lead)
        db.flush()
        created_leads.append(lead)

        # Create activities for each lead
        activity = Activity(
            lead_id=lead.id,
            type="Lead Created",
            description=f"Discovered via prospecting: {contacts[ld['contact_idx']].first_name} at {companies[contacts_data[ld['contact_idx']]['company_idx']].name}",
        )
        db.add(activity)

    db.flush()

    # Add more activities for specific leads
    extra_activities = [
        (0, "Signals Detected", "Signal scan: hiring AI engineers, digital transformation. Score: 82"),
        (0, "Email Sent", "Initial outreach sent: Exploring AI solutions for Apollo Hospitals"),
        (1, "Signals Detected", "Signal scan: cloud adoption, tech partnerships. Score: 68"),
        (1, "Email Sent", "Initial outreach sent to priya.sharma@apollohospitals.com"),
        (1, "Reply Received", "Intent: Interested. Sentiment: positive. Wants to learn more."),
        (2, "Signals Detected", "Signal scan: AI initiatives, hiring data scientists. Score: 91"),
        (2, "Email Sent", "Initial outreach sent to shashank@practo.com"),
        (2, "Reply Received", "Intent: Meeting Request. Sentiment: positive."),
        (2, "Meeting Scheduled", "Auto-booked demo meeting. Google Meet link generated."),
        (3, "Signals Detected", "Signal scan: hospital expansion, funding round. Score: 75"),
        (3, "Email Sent", "Initial outreach sent to dharmil@pharmeasy.in"),
        (3, "Reply Received", "Intent: Pricing Request. Sentiment: neutral."),
        (3, "Proposal Sent", "Custom pricing proposal sent."),
        (5, "Signals Detected", "Signal scan: digital transformation. Score: 95"),
        (5, "Email Sent", "Initial outreach sent to atul@medlife.com"),
        (5, "Reply Received", "Intent: Demo Request. Sentiment: positive."),
        (5, "Meeting Scheduled", "Demo meeting completed."),
        (5, "Proposal Sent", "Enterprise proposal sent."),
        (5, "Deal Closed", "Deal closed won: $95,000 annual contract."),
    ]

    for lead_idx, act_type, act_desc in extra_activities:
        activity = Activity(
            lead_id=created_leads[lead_idx].id,
            type=act_type,
            description=act_desc,
        )
        db.add(activity)

    # Emails
    emails = [
        Email(lead_id=created_leads[0].id, subject="Exploring AI solutions for Apollo Hospitals",
              body="Hi Rajesh...", status="sent", from_email="sales@setv.ai",
              to_email="rajesh@apollohospitals.com"),
        Email(lead_id=created_leads[1].id, subject="AI-powered sales automation for Apollo",
              body="Hi Priya...", status="sent", from_email="sales@setv.ai",
              to_email="priya.sharma@apollohospitals.com"),
        Email(lead_id=created_leads[2].id, subject="SETV for Practo — AI sales platform",
              body="Hi Shashank...", status="sent", from_email="sales@setv.ai",
              to_email="shashank@practo.com"),
    ]
    for e in emails:
        db.add(e)

    # Meetings
    meeting = Meeting(
        lead_id=created_leads[2].id,
        title="Demo — SETV AI Platform for Practo",
        scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
        status="scheduled",
    )
    db.add(meeting)

    # Replies
    replies = [
        Reply(lead_id=created_leads[1].id, message_id="reply-001",
              content="This sounds interesting! Can you tell me more about the pricing?",
              intent="Interested", sentiment="positive", processed=True),
        Reply(lead_id=created_leads[2].id, message_id="reply-002",
              content="Yes, let's schedule a demo. How about next Tuesday?",
              intent="Meeting Request", sentiment="positive", processed=True),
    ]
    for r in replies:
        db.add(r)

    db.commit()
    print(f"✅ Seeded: {len(companies)} companies, {len(contacts)} contacts, "
          f"{len(created_leads)} leads, {len(extra_activities)} activities, "
          f"{len(emails)} emails, 1 meeting, {len(replies)} replies")


def verify_routes():
    """Verify all API routes return valid responses."""
    import requests

    base = "http://localhost:8000"
    print("\n🔍 Verifying API routes...")

    routes = [
        ("GET", "/health", 200),
        ("GET", "/leads", 200),
        ("GET", "/campaigns", 200),
        ("GET", "/meetings", 200),
        ("GET", "/pipeline/report", 200),
    ]

    all_passed = True
    for method, path, expected_status in routes:
        try:
            resp = requests.request(method, f"{base}{path}", timeout=5)
            status = "✅" if resp.status_code == expected_status else "❌"
            if resp.status_code != expected_status:
                all_passed = False
            print(f"  {status} {method} {path} → {resp.status_code}")

            # Show some data for key routes
            if path == "/pipeline/report" and resp.status_code == 200:
                data = resp.json()
                print(f"      Lead Funnel: {data.get('lead_funnel', {})}")
                print(f"      Pipeline Value: ${data.get('pipeline_forecast', {}).get('total_value', 0):,.0f}")
                print(f"      Risk Flags: {len(data.get('risk_flags', []))}")
                print(f"      Stalled Deals: {len(data.get('stalled_deals', []))}")
                print(f"      Next Actions: {len(data.get('next_best_actions', []))}")
            elif path == "/leads" and resp.status_code == 200:
                data = resp.json()
                print(f"      Total leads: {data.get('total', 0)}")

        except requests.ConnectionError:
            print(f"  ❌ {method} {path} → Connection refused (is the server running?)")
            all_passed = False
        except Exception as e:
            print(f"  ❌ {method} {path} → Error: {e}")
            all_passed = False

    if all_passed:
        print("\n🎉 All route verifications passed!")
    else:
        print("\n⚠️  Some routes failed. Make sure the FastAPI server is running.")

    return all_passed


if __name__ == "__main__":
    import os
    os.environ.setdefault("DATABASE_URL", "sqlite:///./setv_demo.db")

    # Recreate tables
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_data(db)
    finally:
        db.close()

    # Only verify routes if server flag is passed
    if "--verify" in sys.argv:
        verify_routes()
    else:
        print("\n💡 Run the FastAPI server and then use --verify to test routes:")
        print("   uvicorn apps.api.main:app --reload")
        print("   python -m apps.api.seed.e2e_verify --verify")
