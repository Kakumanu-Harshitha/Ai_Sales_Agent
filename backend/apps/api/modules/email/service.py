from email.message import EmailMessage
import base64
import smtplib
import re
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session
from apps.api.core.config import settings
from apps.api.modules.crm.models import Contact, Lead, Activity, Email, Reply

def get_email_body(payload):
    """Recursively extract plain text body from Gmail payload."""
    if 'data' in payload.get('body', {}):
        return base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
    
    parts = payload.get('parts', [])
    for part in parts:
        if part['mimeType'] == 'text/plain':
            if 'data' in part['body']:
                return base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
        elif 'parts' in part:
            found = get_email_body(part)
            if found:
                return found
    return ""

def extract_clean_body(raw_text: str) -> str:
    if not raw_text:
        return ""
    # Simple regex to strip Gmail style quotes
    cleaned = re.split(r'\r?\nOn .*? wrote:', raw_text, flags=re.IGNORECASE)[0]
    cleaned = re.split(r'\r?\n>+', cleaned)[0]
    cleaned = re.split(r'\r?\n---.*Forwarded message', cleaned, flags=re.IGNORECASE)[0]
    # Remove some common signature delimiters
    cleaned = re.split(r'\r?\n-- \r?\n', cleaned)[0]
    return cleaned.strip()

class EmailService:
    def __init__(self, db: Session):
        self.db = db

    def get_gmail_service(self):
        from apps.api.core.google_auth import get_google_credentials
        creds = get_google_credentials()
        if not creds:
            return None
        return build('gmail', 'v1', credentials=creds)

    def _send_via_gmail(self, to: str, subject: str, body: str, from_email: str, thread_id: str = None, in_reply_to: str = None):
        service = self.get_gmail_service()
        if not service:
            raise Exception("Gmail API not configured")
            
        message = EmailMessage()
        message.set_content(body)
        message['To'] = to
        message['From'] = from_email
        message['Subject'] = subject
        
        if in_reply_to:
            message['In-Reply-To'] = in_reply_to
            message['References'] = in_reply_to
            
        encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
        create_message = {'raw': encoded_message}
        
        if thread_id:
            create_message['threadId'] = thread_id
            
        send_message = (service.users().messages().send(userId="me", body=create_message).execute())
        return send_message

    def _send_via_smtp(self, to: str, subject: str, body: str, from_email: str):
        if not getattr(settings, 'SMTP_HOST', None):
            raise Exception("SMTP not configured")
        
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = from_email
        msg['To'] = to
        
        port = getattr(settings, 'SMTP_PORT', 587)
        port = int(port) if port else 587
            
        with smtplib.SMTP(settings.SMTP_HOST, port) as server:
            if getattr(settings, 'SMTP_USER', None) and getattr(settings, 'SMTP_PASSWORD', None):
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True

    def send_email(self, to: str, subject: str, body: str, from_email: str, lead_id: int = None, thread_id: str = None, in_reply_to: str = None):
        gmail_msg_id = None
        try:
            res = self._send_via_gmail(to, subject, body, from_email, thread_id, in_reply_to)
            status = "sent"
            gmail_msg_id = res.get('id')
        except Exception as e:
            try:
                self._send_via_smtp(to, subject, body, from_email)
                status = "sent"
            except Exception as smtp_e:
                status = "failed"
                raise Exception(f"Failed to send email: {e}, {smtp_e}")

        email_record = Email(
            lead_id=lead_id,
            subject=subject,
            body=body,
            status=status,
            from_email=from_email,
            to_email=to,
            gmail_message_id=gmail_msg_id
        )
        self.db.add(email_record)
        
        if lead_id:
            activity = Activity(
                lead_id=lead_id,
                type="Email Sent",
                description=f"Email sent to {to}: {subject}"
            )
            self.db.add(activity)
            
        self.db.flush()
        return email_record

    def fetch_incoming_replies(self):
        service = self.get_gmail_service()
        if not service:
            return []
            
        import logging
        logger = logging.getLogger(__name__)
            
        try:
            results = service.users().messages().list(userId='me', q="is:unread").execute()
            messages = results.get('messages', [])
            
            processed_replies = []
            for msg in messages:
                msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
                
                headers = msg_data['payload']['headers']
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), "No Subject")
                from_header = next((h['value'] for h in headers if h['name'].lower() == 'from'), "")
                message_id = next((h['value'] for h in headers if h['name'].lower() == 'message-id'), msg['id'])
                
                in_reply_to = next((h['value'] for h in headers if h['name'].lower() == 'in-reply-to'), None)
                references = next((h['value'] for h in headers if h['name'].lower() == 'references'), None)
                thread_id = msg_data.get('threadId')
                
                existing = self.db.query(Reply).filter(Reply.message_id == message_id).first()
                if existing:
                    continue
                    
                email_match = re.search(r'[\w\.-]+@[\w\.-]+', from_header)
                sender_email = email_match.group(0) if email_match else from_header
                
                name_match = re.search(r'^(.*?)\s*<', from_header)
                sender_name = name_match.group(1).strip() if name_match else sender_email
                
                snippet = msg_data.get('snippet', '')
                
                raw_body = get_email_body(msg_data['payload'])
                clean_body = extract_clean_body(raw_body)
                
                lead_id = None
                matched_email = None
                
                if thread_id:
                    matched_email = self.db.query(Email).filter(Email.gmail_message_id == thread_id).first()
                
                if not matched_email and in_reply_to:
                    clean_in_reply_to = in_reply_to.strip('<>')
                    matched_email = self.db.query(Email).filter(Email.gmail_message_id == clean_in_reply_to).first()
                    
                if not matched_email and references:
                    ref_ids = [r.strip('<>') for r in references.split()]
                    matched_email = self.db.query(Email).filter(Email.gmail_message_id.in_(ref_ids)).first()
                    
                if not matched_email:
                    contact = self.db.query(Contact).filter(Contact.email == sender_email).first()
                    if contact:
                        lead = self.db.query(Lead).filter(Lead.contact_id == contact.id).first()
                        if lead:
                            matched_email = self.db.query(Email).filter(Email.lead_id == lead.id).first()
                
                if matched_email:
                    lead_id = matched_email.lead_id
                        
                reply = Reply(
                    lead_id=lead_id,
                    thread_id=thread_id,
                    message_id=message_id,
                    gmail_message_id=msg['id'],
                    sender_email=sender_email,
                    sender_name=sender_name,
                    subject=subject,
                    raw_body=raw_body,
                    clean_body=clean_body,
                    content=snippet,
                    processed=False,
                    is_archived=False,
                    is_deleted=False
                )
                self.db.add(reply)
                
                if lead_id:
                    activity = Activity(
                        lead_id=lead_id,
                        type="Reply Received",
                        description=f"Reply from {sender_email}: {subject}"
                    )
                    self.db.add(activity)
                
                try:
                    self.db.commit()
                except Exception as e:
                    self.db.rollback()
                    logger.error(f"Failed to commit reply {message_id} to DB: {e}")
                    continue
                
                processed_replies.append(reply)
                
                try:
                    service.users().messages().modify(
                        userId='me', id=msg['id'], body={'removeLabelIds': ['UNREAD']}
                    ).execute()
                except Exception as e:
                    logger.error(f"Gmail API error removing UNREAD for message {msg['id']}: {e}")

            return processed_replies
        except Exception as e:
            raise e

    def get_unprocessed_replies(self):
        return self.db.query(Reply).filter(Reply.processed == False, Reply.is_deleted == False).all()

    def mark_reply_processed(self, reply_id: int):
        reply = self.db.query(Reply).filter(Reply.id == reply_id).first()
        if reply:
            reply.processed = True
            self.db.flush()
        return reply
