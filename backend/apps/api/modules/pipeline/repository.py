"""
Pipeline module — PostgreSQL aggregation queries for the pipeline report.
All data is computed from existing CRM tables, not stored separately.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func, case
from datetime import datetime, timezone, timedelta
from apps.api.modules.crm.models import Lead, Email, Activity, Meeting, Campaign, Contact


class PipelineRepository:

    # ── Lead Funnel ──────────────────────────────────────────────────────

    def get_lead_funnel(self, db: Session) -> dict:
        """Count leads in each pipeline stage."""
        stages = [
            "new", "scored", "contacted", "replied",
            "meeting_booked", "proposal_sent", "closed_won", "closed_lost",
        ]
        counts = (
            db.query(Lead.status, func.count(Lead.id))
            .group_by(Lead.status)
            .all()
        )
        funnel = {s: 0 for s in stages}
        for status, count in counts:
            key = status.lower() if status else "new"
            if key in funnel:
                funnel[key] = count
            else:
                # Handle legacy status values (e.g. "NEW" → "new")
                funnel.setdefault(key, count)
        return funnel

    # ── Stalled Deals ────────────────────────────────────────────────────

    def get_stalled_deals(self, db: Session, max_days_in_stage: int = 14) -> list[str]:
        """
        Flag deals that have stayed in the same stage for more than
        `max_days_in_stage` days.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(days=max_days_in_stage)
        stalled = (
            db.query(Lead)
            .filter(
                Lead.stage_entered_at < cutoff,
                Lead.status.notin_(["closed_won", "closed_lost", "new"]),
            )
            .all()
        )
        results = []
        for lead in stalled:
            stage_time = lead.stage_entered_at.replace(tzinfo=None) if lead.stage_entered_at else now
            days = (now - stage_time).days
            contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
            name = f"{contact.first_name} {contact.last_name}" if contact else f"Lead #{lead.id}"
            results.append(
                f"{name} (Lead #{lead.id}) — stuck in '{lead.status}' for {days} days"
            )
        return results

    # ── Risk Flags ───────────────────────────────────────────────────────

    def get_risk_flags(self, db: Session, max_inactive_days: int = 10) -> list[str]:
        """
        Flag leads with no activity in more than `max_inactive_days`.
        """
        now = datetime.utcnow()
        cutoff = now - timedelta(days=max_inactive_days)
        at_risk = (
            db.query(Lead)
            .filter(
                Lead.last_activity_at < cutoff,
                Lead.status.notin_(["closed_won", "closed_lost"]),
            )
            .all()
        )
        results = []
        for lead in at_risk:
            activity_time = lead.last_activity_at.replace(tzinfo=None) if lead.last_activity_at else now
            days = (now - activity_time).days
            results.append(
                f"Lead #{lead.id} — no activity for {days} days (status: {lead.status})"
            )
        return results

    # ── Campaign Performance ─────────────────────────────────────────────

    def get_campaign_performance(self, db: Session) -> dict:
        """Aggregate email tracking metrics."""
        total_sent = db.query(Email).filter(Email.status == "sent").count()
        total_opened = db.query(Email).filter(Email.opened_at.isnot(None)).count()
        total_clicked = db.query(Email).filter(Email.clicked_at.isnot(None)).count()
        total_replied = db.query(Email).filter(Email.replied_at.isnot(None)).count()

        return {
            "sent": total_sent,
            "opened": total_opened,
            "clicked": total_clicked,
            "replied": total_replied,
        }

    # ── Pipeline & Revenue Forecast ──────────────────────────────────────

    def get_pipeline_forecast(self, db: Session) -> dict:
        """
        Compute total and weighted pipeline value.
        Weight is based on stage proximity to close.
        """
        stage_weights = {
            "new": 0.05,
            "scored": 0.10,
            "contacted": 0.20,
            "replied": 0.35,
            "meeting_booked": 0.50,
            "proposal_sent": 0.75,
            "closed_won": 1.0,
            "closed_lost": 0.0,
        }

        leads = (
            db.query(Lead)
            .filter(Lead.status.notin_(["closed_won", "closed_lost"]))
            .all()
        )

        total_value = 0.0
        weighted_value = 0.0
        for lead in leads:
            deal = lead.deal_value or 0.0
            weight = stage_weights.get(lead.status, 0.1)
            total_value += deal
            weighted_value += deal * weight

        close_prob = (weighted_value / total_value * 100) if total_value > 0 else 0.0

        return {
            "total_value": round(total_value, 2),
            "weighted_value": round(weighted_value, 2),
            "close_probability": round(close_prob, 2),
        }

    def get_revenue_forecast(self, db: Session) -> dict:
        """Revenue from closed_won deals + weighted open pipeline."""
        closed_won_revenue = (
            db.query(func.coalesce(func.sum(Lead.deal_value), 0.0))
            .filter(Lead.status == "closed_won")
            .scalar()
        )
        pipeline = self.get_pipeline_forecast(db)

        return {
            "expected_revenue": round(float(closed_won_revenue) + pipeline["weighted_value"], 2),
            "forecast_period": "next_30_days",
        }

    # ── Conversion Rates ─────────────────────────────────────────────────

    def get_conversion_rates(self, db: Session) -> dict:
        """Compute stage-to-stage conversion rates."""
        funnel = self.get_lead_funnel(db)

        total_contacted = funnel.get("contacted", 0) + funnel.get("replied", 0) + funnel.get("meeting_booked", 0) + funnel.get("proposal_sent", 0) + funnel.get("closed_won", 0)
        total_replied = funnel.get("replied", 0) + funnel.get("meeting_booked", 0) + funnel.get("proposal_sent", 0) + funnel.get("closed_won", 0)
        total_meeting = funnel.get("meeting_booked", 0) + funnel.get("proposal_sent", 0) + funnel.get("closed_won", 0)
        total_closed = funnel.get("closed_won", 0)

        outreach_to_reply = (total_replied / total_contacted * 100) if total_contacted > 0 else 0.0
        reply_to_meeting = (total_meeting / total_replied * 100) if total_replied > 0 else 0.0
        meeting_to_close = (total_closed / total_meeting * 100) if total_meeting > 0 else 0.0

        return {
            "outreach_to_reply": round(outreach_to_reply, 2),
            "reply_to_meeting": round(reply_to_meeting, 2),
            "meeting_to_close": round(meeting_to_close, 2),
        }
