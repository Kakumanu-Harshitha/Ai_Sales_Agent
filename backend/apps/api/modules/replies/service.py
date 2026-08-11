"""
Replies module — classifies incoming replies using the Reply Handling Agent.
"""

import logging
from sqlalchemy.orm import Session
from .repository import RepliesRepository
from apps.api.core.ai_provider import AIProvider

logger = logging.getLogger(__name__)

REPLY_HANDLING_SYSTEM = """You are a Reply Handling Agent for SETV.
For each reply:
- classify intent
- summarize the reply
- detect sentiment
- extract objections
- assign a priority (High, Medium, Low)
- recommend a next action
- generate a short AI response draft
- output CRM-safe structured JSON

Intent must be exactly one of:
Interested | Pricing Request | Demo Request | Meeting Request | Not Interested | Wrong Person | Out of Office

Draft reply must be under 100 words and sound human.

Return a JSON object with: intent, sentiment, priority, objections (array of strings), summary, recommended_action, draft_reply."""


class RepliesService:
    def __init__(self):
        self.repo = RepliesRepository()

    def classify_reply(self, reply_text: str, outreach_context: str = "") -> dict:
        """
        Call the Reply Handling Agent to classify a reply.
        Returns classification dict or stub fallback.
        """
        prompt = f"""Analyze this reply.
Original Outreach Context: {outreach_context or "None provided"}
Raw Incoming Reply Text:
"{reply_text}"

Generate CRM-safe structured JSON output."""

        result = AIProvider().generate_content(
            system_instruction=REPLY_HANDLING_SYSTEM,
            prompt=prompt,
        )

        if result and result.get("intent"):
            return result

        # Stub fallback — basic keyword classification
        text_lower = reply_text.lower() if reply_text else ""
        priority = "Medium"
        if any(w in text_lower for w in ["interested", "tell me more", "sounds good"]):
            intent = "Interested"
            sentiment = "positive"
            recommended_action = "Send detailed proposal"
            priority = "High"
        elif any(w in text_lower for w in ["price", "cost", "pricing", "quote"]):
            intent = "Pricing Request"
            sentiment = "positive"
            recommended_action = "Send pricing deck"
            priority = "High"
        elif any(w in text_lower for w in ["demo", "demonstration", "show me"]):
            intent = "Demo Request"
            sentiment = "positive"
            recommended_action = "Schedule demo meeting"
            priority = "High"
        elif any(w in text_lower for w in ["meet", "call", "schedule", "calendar"]):
            intent = "Meeting Request"
            sentiment = "positive"
            recommended_action = "Book calendar meeting"
            priority = "High"
        elif any(w in text_lower for w in ["not interested", "no thanks", "unsubscribe", "remove"]):
            intent = "Not Interested"
            sentiment = "negative"
            recommended_action = "Mark as closed_lost and stop outreach"
            priority = "Low"
        elif any(w in text_lower for w in ["wrong person", "not the right", "not me"]):
            intent = "Wrong Person"
            sentiment = "neutral"
            recommended_action = "Find correct contact"
            priority = "Low"
        elif any(w in text_lower for w in ["out of office", "ooo", "vacation", "away"]):
            intent = "Out of Office"
            sentiment = "neutral"
            recommended_action = "Schedule follow-up after return"
            priority = "Low"
        else:
            intent = "Interested"
            sentiment = "neutral"
            recommended_action = "Review manually"

        return {
            "intent": intent,
            "sentiment": sentiment,
            "priority": priority,
            "objections": [],
            "summary": reply_text[:200] if reply_text else "",
            "recommended_action": recommended_action,
            "draft_reply": "Thank you for your response. I'd love to discuss further.",
        }

    def process_unprocessed_replies(self, db: Session, limit: int = 50) -> list[dict]:
        """
        Process all unprocessed replies:
        1. Classify each with AI
        2. Update ReplyAnalysis record
        3. Create CRM activity
        4. Return classification results
        """
        replies = self.repo.get_unprocessed_replies(db, limit)
        results = []

        for reply in replies:
            # use clean_body if available, else raw_body, else fallback to content
            reply_text = reply.clean_body or reply.raw_body or reply.content or ""
            classification = self.classify_reply(reply_text)

            self.repo.mark_processed(db, reply.id, classification)

            if reply.lead_id:
                self.repo.create_activity(
                    db, reply.lead_id, "Reply Received",
                    f"Intent: {classification.get('intent')} | "
                    f"Sentiment: {classification.get('sentiment')} | "
                    f"Priority: {classification.get('priority', 'Medium')} | "
                    f"Summary: {classification.get('summary', '')[:100]}"
                )

            results.append({
                "reply_id": reply.id,
                "lead_id": reply.lead_id,
                "classification": classification,
            })

        db.commit()
        return results
