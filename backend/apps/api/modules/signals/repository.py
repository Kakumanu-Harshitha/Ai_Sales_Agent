"""
Signals module — data access for signals and lead scores.
"""

from sqlalchemy.orm import Session
from datetime import datetime, timezone, timedelta
from apps.api.modules.crm.models import Signal, LeadScore, Activity


from .schemas import SignalCreate

class SignalsRepository:
    def create_signal(self, db: Session, signal_data: SignalCreate) -> Signal:
        signal = Signal(
            lead_id=signal_data.lead_id,
            signal_type=signal_data.signal_type,
            headline=signal_data.headline,
            description=signal_data.description,
            business_impact=signal_data.business_impact,
            why_it_matters=signal_data.why_it_matters,
            source_name=signal_data.source_name,
            source_url=signal_data.source_url,
            source_type=signal_data.source_type,
            published_date=signal_data.published_date,
            confidence_score=signal_data.confidence_score,
            score_contribution=signal_data.score_contribution,
            priority=signal_data.priority,
            recommended_action=signal_data.recommended_action,
            suggested_pitch=signal_data.suggested_pitch,
            target_persona=signal_data.target_persona,
            icp_match=signal_data.icp_match,
        )
        db.add(signal)
        db.flush()
        return signal

    def create_lead_score(self, db: Session, lead_id: int, score: float) -> LeadScore:
        lead_score = LeadScore(
            lead_id=lead_id,
            score=score,
        )
        db.add(lead_score)
        db.flush()
        return lead_score

    def get_signals_for_lead(self, db: Session, lead_id: int):
        return db.query(Signal).filter(Signal.lead_id == lead_id).order_by(Signal.created_at.desc()).all()

    def get_latest_score(self, db: Session, lead_id: int):
        return (
            db.query(LeadScore)
            .filter(LeadScore.lead_id == lead_id)
            .order_by(LeadScore.created_at.desc())
            .first()
        )

    def has_recent_scan(self, db: Session, lead_id: int, hours: int = 24) -> bool:
        """Check if this lead was scanned within the given window."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent = (
            db.query(Signal)
            .filter(Signal.lead_id == lead_id, Signal.created_at >= cutoff)
            .first()
        )
        return recent is not None

    def create_activity(self, db: Session, lead_id: int, activity_type: str, description: str) -> Activity:
        activity = Activity(
            lead_id=lead_id,
            type=activity_type,
            description=description,
        )
        db.add(activity)
        db.flush()
        return activity
