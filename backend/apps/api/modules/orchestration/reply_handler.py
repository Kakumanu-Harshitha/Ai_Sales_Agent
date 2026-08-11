"""
Orchestration — Session 3.2 — Reply Handler

Pipeline: Classify Replies → Book Meetings → Update CRM

For each unprocessed reply:
1. Classify intent/sentiment with AI
2. If Demo/Meeting Request → auto-book a meeting
3. If Not Interested → mark lead as closed_lost
4. All results logged as immutable CRM activities
"""

import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from .schemas import ProcessRepliesRequest, ProcessRepliesResponse
from apps.api.modules.replies.service import RepliesService
from apps.api.modules.replies.repository import RepliesRepository
from apps.api.modules.crm.models import Lead, Contact, Meeting, Activity

logger = logging.getLogger(__name__)


class ReplyHandlerService:
    def __init__(self):
        self.replies_service = RepliesService()
        self.replies_repo = RepliesRepository()

    def process_replies_pipeline(
        self, db: Session, request: ProcessRepliesRequest
    ) -> ProcessRepliesResponse:
        """
        Full reply processing pipeline:
        1. Classify all unprocessed replies
        2. Route based on intent
        3. Book meetings for Demo/Meeting Requests
        4. Update CRM for all intents
        """
        details = []
        meetings_booked = 0
        leads_updated = 0

        # Step 1: Classify
        classified = self.replies_service.process_unprocessed_replies(
            db, limit=request.max_replies
        )

        if not classified:
            return ProcessRepliesResponse(
                status="completed",
                replies_processed=0,
                details=[{"step": "classify", "message": "No unprocessed replies found"}],
            )

        # Step 2: Route by intent
        for item in classified:
            lead_id = item.get("lead_id")
            classification = item.get("classification", {})
            intent = classification.get("intent", "")

            if not lead_id:
                details.append({
                    "reply_id": item.get("reply_id"),
                    "intent": intent,
                    "action": "skipped — no lead_id",
                })
                continue

            if intent in ("Demo Request", "Meeting Request"):
                # Auto-book meeting
                meeting_result = self._book_meeting_for_lead(db, lead_id, intent)
                if meeting_result:
                    meetings_booked += 1
                    details.append({
                        "lead_id": lead_id,
                        "intent": intent,
                        "action": "meeting_booked",
                        "meeting_id": meeting_result.get("meeting_id"),
                    })
                else:
                    details.append({
                        "lead_id": lead_id,
                        "intent": intent,
                        "action": "meeting_booking_failed",
                    })

                self.replies_repo.update_lead_status(db, lead_id, "meeting_booked")
                leads_updated += 1

            elif intent in ("Interested", "Pricing Request"):
                self.replies_repo.update_lead_status(db, lead_id, "replied")
                leads_updated += 1
                details.append({
                    "lead_id": lead_id,
                    "intent": intent,
                    "action": "marked_replied",
                })

            elif intent == "Not Interested":
                self.replies_repo.update_lead_status(db, lead_id, "closed_lost")
                leads_updated += 1
                details.append({
                    "lead_id": lead_id,
                    "intent": intent,
                    "action": "marked_closed_lost",
                })

            elif intent == "Wrong Person":
                self.replies_repo.create_activity(
                    db, lead_id, "Wrong Contact",
                    "Reply from wrong person — need to find correct contact."
                )
                details.append({
                    "lead_id": lead_id,
                    "intent": intent,
                    "action": "flagged_wrong_person",
                })

            elif intent == "Out of Office":
                self.replies_repo.create_activity(
                    db, lead_id, "Out of Office",
                    "Contact is out of office. Will follow up after return."
                )
                details.append({
                    "lead_id": lead_id,
                    "intent": intent,
                    "action": "noted_ooo",
                })

            else:
                details.append({
                    "lead_id": lead_id,
                    "intent": intent,
                    "action": "no_specific_routing",
                })

        db.commit()

        return ProcessRepliesResponse(
            status="completed",
            replies_processed=len(classified),
            meetings_booked=meetings_booked,
            leads_updated=leads_updated,
            details=details,
        )

    def _book_meeting_for_lead(self, db: Session, lead_id: int, intent: str) -> dict | None:
        """
        Book a meeting for a lead.
        Uses the meetings module if Google Calendar is configured.
        Falls back to creating a local meeting record.
        """
        try:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if not lead:
                return None

            # Calculate next available slot (simplified: tomorrow at 10am)
            tomorrow = datetime.now(timezone.utc).replace(
                hour=10, minute=0, second=0, microsecond=0
            ) + timedelta(days=1)

            # Create local meeting record (Google Calendar booking can be
            # triggered separately via POST /calendar/book if OAuth is configured)
            meeting = Meeting(
                lead_id=lead_id,
                scheduled_at=tomorrow,
                status="scheduled",
                title=f"{intent} — SETV AI Platform",
            )
            db.add(meeting)
            db.flush()

            # Immutable CRM activity
            activity = Activity(
                lead_id=lead_id,
                type="Meeting Scheduled",
                description=f"Auto-booked after '{intent}' reply. "
                            f"Scheduled: {tomorrow.isoformat()}",
            )
            db.add(activity)
            db.flush()

            return {"meeting_id": meeting.id, "scheduled_at": tomorrow.isoformat()}

        except Exception as e:
            logger.error(f"Failed to book meeting for lead {lead_id}: {e}", exc_info=True)
            return None
