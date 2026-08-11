from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from apps.api.db.database import get_db
from apps.api.modules.crm.models import Reply, ReplyAnalysis, Activity, Lead, Email, Contact, Company, Meeting, Call, Note
from apps.api.modules.email.service import EmailService
from datetime import datetime, timezone

router = APIRouter(prefix='/replies', tags=['Replies'])

class RespondRequest(BaseModel):
    body: str

class ActionRequest(BaseModel):
    action: str  # "archive", "delete", "mark_read", "mark_unread"

@router.get('/inbox')
def get_inbox_leads(db: Session = Depends(get_db)):
    """
    Returns a list of leads that have active replies (not archived, not deleted).
    Groups by lead_id, fetching the latest reply and its analysis.
    """
    replies = db.query(Reply).filter(Reply.is_deleted == False, Reply.is_archived == False).all()
    
    lead_map = {}
    for r in replies:
        if r.lead_id not in lead_map:
            lead_map[r.lead_id] = []
        lead_map[r.lead_id].append(r)
        
    inbox_items = []
    
    for lead_id, lead_replies in lead_map.items():
        if not lead_id:
            continue
            
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            continue
            
        contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
        company = db.query(Company).filter(Company.id == contact.company_id).first() if contact else None
        
        # Sort to get latest
        lead_replies.sort(key=lambda x: x.received_at, reverse=True)
        latest_reply = lead_replies[0]
        
        analysis = db.query(ReplyAnalysis).filter(ReplyAnalysis.reply_id == latest_reply.id).first()
        
        unread_count = sum(1 for rep in lead_replies if not rep.processed)
        
        inbox_items.append({
            'lead_id': lead.id,
            'lead_name': f"{contact.first_name or ''} {contact.last_name or ''}".strip() if contact else "Unknown",
            'company_name': company.name if company else "Unknown",
            'email': contact.email if contact else "",
            'lead_score': lead.lead_score,
            'lead_status': lead.status,
            'latest_reply_time': str(latest_reply.received_at),
            'unread_count': unread_count,
            'subject': latest_reply.subject,
            'clean_body': latest_reply.clean_body or latest_reply.raw_body or latest_reply.content,
            'intent': analysis.intent if analysis else None,
            'sentiment': analysis.sentiment if analysis else None,
            'priority': analysis.priority if analysis else 'Medium',
            'latest_reply_id': latest_reply.id
        })
        
    # Sort inbox by latest reply first
    inbox_items.sort(key=lambda x: x['latest_reply_time'], reverse=True)
    return inbox_items


@router.get('/inbox/{lead_id}/history')
def get_lead_history(lead_id: int, db: Session = Depends(get_db)):
    """
    Returns a unified chronological timeline for a specific lead.
    """
    timeline = []
    
    # 1. Replies
    replies = db.query(Reply).filter(Reply.lead_id == lead_id, Reply.is_deleted == False).all()
    for r in replies:
        analysis = db.query(ReplyAnalysis).filter(ReplyAnalysis.reply_id == r.id).first()
        a_dict = {
            'intent': analysis.intent,
            'sentiment': analysis.sentiment,
            'priority': analysis.priority,
            'recommended_action': analysis.recommended_action,
            'reply_draft': analysis.reply_draft,
            'objections': analysis.objections
        } if analysis else None
        
        timeline.append({
            'type': 'reply',
            'timestamp': str(r.received_at),
            'data': {
                'id': r.id,
                'subject': r.subject,
                'sender_name': r.sender_name,
                'sender_email': r.sender_email,
                'body': r.clean_body or r.raw_body or r.content,
                'is_archived': r.is_archived,
                'processed': r.processed,
                'analysis': a_dict
            }
        })
        
    # 2. Outbound Emails
    emails = db.query(Email).filter(Email.lead_id == lead_id).all()
    for e in emails:
        timeline.append({
            'type': 'email',
            'timestamp': str(e.sent_at),
            'data': {
                'subject': e.subject,
                'body': e.body,
                'status': e.status,
                'to_email': e.to_email
            }
        })
        
    # 3. Meetings
    meetings = db.query(Meeting).filter(Meeting.lead_id == lead_id).all()
    for m in meetings:
        timeline.append({
            'type': 'meeting',
            'timestamp': str(m.created_at),
            'data': {
                'title': m.title,
                'scheduled_at': str(m.scheduled_at) if m.scheduled_at else None,
                'status': m.status
            }
        })
        
    # 4. Calls
    calls = db.query(Call).filter(Call.lead_id == lead_id).all()
    for c in calls:
        timeline.append({
            'type': 'call',
            'timestamp': str(c.created_at),
            'data': {
                'outcome': c.outcome,
                'notes': c.notes,
                'duration': getattr(c, 'duration_minutes', 0)
            }
        })
        
    # 5. Notes
    notes = db.query(Note).filter(Note.lead_id == lead_id).all()
    for n in notes:
        timeline.append({
            'type': 'note',
            'timestamp': str(n.created_at),
            'data': {
                'content': n.content
            }
        })
        
    # 6. Activities (CRM timeline events, Pipeline Changes)
    activities = db.query(Activity).filter(Activity.lead_id == lead_id).all()
    for a in activities:
        timeline.append({
            'type': 'activity',
            'timestamp': str(a.created_at),
            'data': {
                'activity_type': a.type,
                'description': a.description
            }
        })
        
    timeline.sort(key=lambda x: x['timestamp'])
    return timeline


@router.post('/{reply_id}/action')
def perform_reply_action(reply_id: int, req: ActionRequest, db: Session = Depends(get_db)):
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not reply:
        return {'error': 'Reply not found'}
        
    if req.action == 'archive':
        reply.is_archived = True
    elif req.action == 'delete':
        reply.is_deleted = True
    elif req.action == 'mark_read':
        reply.processed = True
    elif req.action == 'mark_unread':
        reply.processed = False
        
    db.commit()
    return {'status': 'success', 'action': req.action}


@router.post('/{reply_id}/respond')
def respond_to_reply(reply_id: int, req: RespondRequest, db: Session = Depends(get_db)):
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not reply:
        return {'error': 'Reply not found'}
        
    lead = db.query(Lead).filter(Lead.id == reply.lead_id).first()
    if not lead:
        return {'error': 'Lead not found'}
        
    contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
    if not contact:
        return {'error': 'Contact not found'}

    email_service = EmailService(db)
    
    # Use thread_id from the reply, or fallback to gmail_message_id as the In-Reply-To
    try:
        sent_email = email_service.send_email(
            to=contact.email,
            subject=f"Re: {reply.subject or ''}".replace("Re: Re:", "Re:"),
            body=req.body,
            from_email="me",  # Gmail API uses "me"
            lead_id=lead.id,
            thread_id=reply.thread_id,
            in_reply_to=reply.gmail_message_id or reply.message_id
        )
        
        reply.processed = True
        lead.last_activity_at = datetime.now(timezone.utc)
        
        activity = Activity(
            lead_id=lead.id,
            type='Email Replied',
            description=f'Sent manual response to reply: {reply.subject}'
        )
        db.add(activity)
        db.commit()
        
        return {'status': 'success', 'email_id': sent_email.id}
    except Exception as e:
        return {'error': str(e)}
