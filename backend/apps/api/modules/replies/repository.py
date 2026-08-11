"""
Replies module — data access for reply classification and processing.
"""

from sqlalchemy.orm import Session
from apps.api.modules.crm.models import Reply, Activity, Lead, ReplyAnalysis
import json

class RepliesRepository:

    def get_unprocessed_replies(self, db: Session, limit: int = 50):
        return (
            db.query(Reply)
            .filter(Reply.processed == False, Reply.is_deleted == False)
            .order_by(Reply.created_at.asc())
            .limit(limit)
            .all()
        )

    def mark_processed(self, db: Session, reply_id: int, classification: dict):
        reply = db.query(Reply).filter(Reply.id == reply_id).first()
        if reply:
            reply.processed = True
            
            analysis = db.query(ReplyAnalysis).filter(ReplyAnalysis.reply_id == reply_id).first()
            if not analysis:
                analysis = ReplyAnalysis(reply_id=reply_id)
                db.add(analysis)
                
            analysis.intent = classification.get("intent")
            analysis.sentiment = classification.get("sentiment")
            
            obj = classification.get("objections", [])
            if not isinstance(obj, list):
                obj = [obj] if obj else []
            analysis.objections = json.dumps(obj)
            
            analysis.summary = classification.get("summary")
            analysis.priority = classification.get("priority", "Medium")
            
            # Map next_action from old prompt if recommended_action is missing
            analysis.recommended_action = classification.get("recommended_action") or classification.get("next_action")
            analysis.reply_draft = classification.get("draft_reply") or classification.get("reply_draft")
            
            db.flush()
        return reply

    def update_lead_status(self, db: Session, lead_id: int, new_status: str):
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if lead:
            from datetime import datetime, timezone
            lead.status = new_status
            lead.stage_entered_at = datetime.now(timezone.utc)
            lead.last_activity_at = datetime.now(timezone.utc)
            db.flush()

    def create_activity(self, db: Session, lead_id: int, activity_type: str, description: str):
        activity = Activity(
            lead_id=lead_id,
            type=activity_type,
            description=description,
        )
        db.add(activity)
        db.flush()
        return activity
