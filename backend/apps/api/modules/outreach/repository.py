"""
Outreach module — data access for follow-up outreach.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timezone, timedelta
from apps.api.modules.crm.models import Lead, Email, LinkedinMessage, Activity


class OutreachRepository:
    def get_leads_needing_followup(self, db: Session, days_inactive: int = 3):
        """
        Find leads in 'contacted' status with no activity
        in the last `days_inactive` days, AND who have actually received an email.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_inactive)
        return (
            db.query(Lead)
            .join(Email, Lead.id == Email.lead_id)
            .filter(
                Lead.status == "contacted",
                Lead.last_activity_at < cutoff,
                Email.status == "sent"
            )
            .distinct()
            .all()
        )

    def get_outreach_count_for_lead(self, db: Session, lead_id: int) -> int:
        """Count how many outreach emails have been sent to this lead."""
        return db.query(Email).filter(Email.lead_id == lead_id).count()

    def has_outreach_at_step(self, db: Session, lead_id: int, step_number: int) -> bool:
        """
        Check if an outreach email already exists for this lead at the given step.
        Used for idempotency in the follow-up job.
        """
        # We encode step info in the subject line prefix for simplicity
        email = (
            db.query(Email)
            .filter(
                Email.lead_id == lead_id,
                Email.subject.like(f"[Follow-up #{step_number}]%"),
            )
            .first()
        )
        return email

    def create_outreach_email(
        self, db: Session, lead_id: int, subject: str, body: str,
        to_email: str, from_email: str = "noreply@setv.ai", html_body: str = None
    ) -> Email:
        email = Email(
            lead_id=lead_id,
            subject=subject,
            body=body,
            html_body=html_body,
            status="draft",
            from_email=from_email,
            to_email=to_email,
        )
        db.add(email)
        db.flush()
        return email

    def create_activity(self, db: Session, lead_id: int, activity_type: str, description: str) -> Activity:
        activity = Activity(
            lead_id=lead_id,
            type=activity_type,
            description=description,
        )
        db.add(activity)
        db.flush()
        return activity
