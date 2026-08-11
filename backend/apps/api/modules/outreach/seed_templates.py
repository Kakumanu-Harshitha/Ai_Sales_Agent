"""
Migration: Add outreach_templates table and seed default templates.
Run from project root: python apps/api/modules/outreach/seed_templates.py
"""
import sys
import os
# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..')))

from apps.api.db.database import engine, SessionLocal
from apps.api.modules.crm.models import Base, OutreachTemplate
import sqlalchemy

DEFAULT_TEMPLATES = [
    {
        "name": "Cold Outreach",
        "subject": "Transforming {{industry}} Operations at {{company_name}} with AI",
        "body": """Dear {{contact_name}},

I hope this message finds you well. My name is {{sender_name}}, and I'm reaching out from SETV — we specialize in AI-powered solutions designed specifically for the {{industry}} sector.

I came across {{company_name}} and was impressed by your work in {{city}}, {{state}}. We've been helping organizations like yours streamline operations and improve patient outcomes using intelligent automation.

I'd love to share how SETV can specifically benefit {{company_name}}. Would you be open to a brief 15-minute conversation this week?

Looking forward to connecting.

Warm regards,
{{sender_name}}""",
        "category": "Prospecting",
        "is_default": True,
    },
    {
        "name": "Product Introduction",
        "subject": "Introducing SETV's AI Healthcare Solution for {{company_name}}",
        "body": """Dear {{contact_name}},

Thank you for taking the time to connect. I wanted to share a bit more about what SETV offers and how it could benefit {{company_name}}.

SETV is an AI-driven sales and engagement platform built for the healthcare space. Here's what we bring to the table:

• **Intelligent Lead Discovery** – We identify your ideal prospects across Apollo, NPI, and the open web.
• **AI-Powered Outreach** – Personalized, signal-based email campaigns that resonate.
• **CRM Integration** – Full visibility into your pipeline, from first contact to closed deal.
• **Meeting Automation** – Auto-schedule demos and discovery calls with Google Calendar.

Given {{company_name}}'s focus in {{industry}} and your presence in {{city}}, I believe SETV could deliver measurable ROI within the first quarter.

Would you like a personalized walkthrough of the platform?

Best regards,
{{sender_name}}""",
        "category": "Introduction",
        "is_default": True,
    },
    {
        "name": "Meeting Request",
        "subject": "Quick Call to Discuss AI Opportunities at {{company_name}}?",
        "body": """Dear {{contact_name}},

I'm reaching out because I believe there's a strong opportunity to help {{company_name}} leverage AI to accelerate growth and improve operational efficiency.

We've worked with several {{industry}} organizations in {{state}} and have seen remarkable results — from reducing manual workflows by 40% to tripling outreach response rates.

I'd love to schedule a 20-minute call to:
1. Understand your current challenges and goals.
2. Show you how SETV addresses them specifically for {{industry}}.
3. Explore if there's a fit worth pursuing together.

Are you available for a quick call this week? I'm flexible and happy to work around your schedule.

Looking forward to hearing from you.

Best,
{{sender_name}}""",
        "category": "Scheduling",
        "is_default": True,
    },
    {
        "name": "Follow-up",
        "subject": "Following Up — AI Solutions for {{company_name}}",
        "body": """Dear {{contact_name}},

I wanted to follow up on my previous email regarding how SETV's AI platform could benefit {{company_name}}.

I understand you're busy, so I'll keep this brief — I genuinely believe we can help {{company_name}} in {{city}} solve key challenges in {{industry}} and would love the chance to show you how.

{{buying_signal}}

If now isn't the right time, I completely understand. Just reply with a date that works better, and I'll reach out then.

Thank you for your time,
{{sender_name}}""",
        "category": "Follow-up",
        "is_default": True,
    },
    {
        "name": "Demo Invitation",
        "subject": "You're Invited: Live Demo of SETV AI Platform — Tailored for {{company_name}}",
        "body": """Dear {{contact_name}},

I'd like to personally invite you and your team at {{company_name}} to a live demonstration of the SETV AI platform.

In this 30-minute session, you'll see:
✓ How we discover and qualify leads specific to {{industry}}
✓ AI-generated, personalized outreach that gets responses
✓ Real-time pipeline visibility and deal tracking
✓ Calendar integration and meeting automation

The demo will be customized around {{company_name}}'s profile and the challenges typical of organizations in {{city}}, {{state}}.

**[Book Your Demo Slot →]**

Seats are limited — I'd love to reserve one for you.

Best regards,
{{sender_name}}""",
        "category": "Demo",
        "is_default": True,
    },
    {
        "name": "Thank You",
        "subject": "Thank You for Meeting with Us, {{contact_name}}",
        "body": """Dear {{contact_name}},

Thank you for taking the time to connect with us today. It was a pleasure learning more about {{company_name}} and understanding your goals in the {{industry}} space.

Based on our conversation, here's a quick summary of the key points and agreed next steps:

**What we discussed:**
• {{company_summary}}
• Your current challenges and growth objectives
• How SETV's AI platform can address these needs

**Next Steps:**
1. I'll send over a customized proposal tailored to {{company_name}} within 48 hours.
2. We'll schedule a follow-up call to review the proposal and answer any questions.
3. If it's a fit, we'll move forward with onboarding.

Please don't hesitate to reach out if you have any questions in the meantime. I look forward to building something great together.

Warm regards,
{{sender_name}}""",
        "category": "Post-Meeting",
        "is_default": True,
    },
]


def run():
    # Create the table if it doesn't exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        existing = db.query(OutreachTemplate).filter(OutreachTemplate.is_default == True).count()
        if existing >= 6:
            print(f"Default templates already seeded ({existing} found). Skipping.")
            return

        for t in DEFAULT_TEMPLATES:
            existing_named = db.query(OutreachTemplate).filter(OutreachTemplate.name == t["name"]).first()
            if not existing_named:
                db.add(OutreachTemplate(**t))
                print(f"  Seeding: {t['name']}")

        db.commit()
        print("Done! Default templates seeded successfully.")
    finally:
        db.close()


if __name__ == "__main__":
    run()
