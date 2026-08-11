from fastapi import APIRouter, Depends, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
import shutil
import uuid
import os
from apps.api.db.database import get_db
from .service import OutreachService
from apps.api.modules.crm.models import Email, Campaign, Lead, SignatureTemplate, OutreachTemplate, AgentSettings

router = APIRouter(prefix='/outreach', tags=['Outreach'])
service = OutreachService()


class SignatureTemplateCreate(BaseModel):
    name: str
    full_name: Optional[str] = None
    designation: Optional[str] = None
    company: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    department: Optional[str] = None
    digital_signature_url: Optional[str] = None
    header_banner_url: Optional[str] = None
    footer_banner_url: Optional[str] = None

class GenerateOutreachRequest(BaseModel):
    lead_id: int
    channel: str = 'email'
    signal_summary: Optional[str] = ''
    template_id: Optional[int] = None
    force_new: bool = False


class OutreachTemplateCreate(BaseModel):
    name: str
    subject: Optional[str] = ''
    body: Optional[str] = ''
    category: Optional[str] = 'Custom'


class OutreachTemplateUpdate(BaseModel):
    name: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None


@router.post('/upload')
async def upload_file(file: UploadFile = File(...)):
    ext = file.filename.split('.')[-1]
    filename = f"{uuid.uuid4()}.{ext}"
    filepath = os.path.join("static", "uploads", filename)
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"url": f"http://localhost:8000/static/uploads/{filename}"}

@router.get('/signatures')
def list_signatures(db: Session = Depends(get_db)):
    signatures = db.query(SignatureTemplate).order_by(SignatureTemplate.id).all()
    return signatures

@router.post('/signatures')
def create_signature(req: SignatureTemplateCreate, db: Session = Depends(get_db)):
    sig = SignatureTemplate(**req.dict())
    db.add(sig)
    db.commit()
    db.refresh(sig)
    return sig

@router.put('/signatures/{sig_id}')
def update_signature(sig_id: int, req: SignatureTemplateCreate, db: Session = Depends(get_db)):
    sig = db.query(SignatureTemplate).filter(SignatureTemplate.id == sig_id).first()
    if not sig:
        return {"error": "Not found"}
    for k, v in req.dict().items():
        setattr(sig, k, v)
    db.commit()
    db.refresh(sig)
    return sig

@router.post('/generate')
def generate_outreach(req: GenerateOutreachRequest, db: Session = Depends(get_db)):
    # Load template if provided
    template = None
    if req.template_id:
        template = db.query(OutreachTemplate).filter(OutreachTemplate.id == req.template_id).first()
    else:
        settings = db.query(AgentSettings).first()
        if settings and settings.default_outreach_template_id:
            template = db.query(OutreachTemplate).filter(OutreachTemplate.id == settings.default_outreach_template_id).first()
    result = service.generate_initial_outreach(
        db, req.lead_id, req.signal_summary or '', req.channel,
        template=template, force_new=req.force_new
    )
    db.commit()
    return result


# ── OUTREACH TEMPLATES ────────────────────────────────────────────────────────

@router.get('/templates')
def list_templates(db: Session = Depends(get_db)):
    templates = db.query(OutreachTemplate).order_by(
        OutreachTemplate.is_default.desc(), OutreachTemplate.created_at.asc()
    ).all()
    settings = db.query(AgentSettings).first()
    default_id = settings.default_outreach_template_id if settings else None
    return [
        {
            'id': t.id, 'name': t.name, 'subject': t.subject, 'body': t.body,
            'category': t.category, 'is_default': t.is_default,
            'is_set_as_default': t.id == default_id,
            'created_at': str(t.created_at), 'updated_at': str(t.updated_at)
        }
        for t in templates
    ]


@router.post('/templates')
def create_template(req: OutreachTemplateCreate, db: Session = Depends(get_db)):
    t = OutreachTemplate(name=req.name, subject=req.subject, body=req.body,
                         category=req.category, is_default=False)
    db.add(t)
    db.commit()
    db.refresh(t)
    return {'id': t.id, 'name': t.name, 'subject': t.subject, 'body': t.body,
            'category': t.category, 'is_default': t.is_default,
            'created_at': str(t.created_at), 'updated_at': str(t.updated_at)}


@router.put('/templates/{template_id}')
def update_template(template_id: int, req: OutreachTemplateUpdate, db: Session = Depends(get_db)):
    t = db.query(OutreachTemplate).filter(OutreachTemplate.id == template_id).first()
    if not t:
        return {'error': 'Template not found'}
    if t.is_default:
        return {'error': 'Cannot edit a built-in template. Duplicate it first.'}
    if req.name is not None: t.name = req.name
    if req.subject is not None: t.subject = req.subject
    if req.body is not None: t.body = req.body
    if req.category is not None: t.category = req.category
    db.commit()
    db.refresh(t)
    return {'id': t.id, 'name': t.name, 'subject': t.subject, 'body': t.body,
            'category': t.category, 'is_default': t.is_default,
            'created_at': str(t.created_at), 'updated_at': str(t.updated_at)}


@router.delete('/templates/{template_id}')
def delete_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(OutreachTemplate).filter(OutreachTemplate.id == template_id).first()
    if not t:
        return {'error': 'Template not found'}
    if t.is_default:
        return {'error': 'Cannot delete a built-in template.'}
    # Clear default pointer if this template was the default
    settings = db.query(AgentSettings).first()
    if settings and settings.default_outreach_template_id == template_id:
        settings.default_outreach_template_id = None
    db.delete(t)
    db.commit()
    return {'deleted': template_id}


@router.post('/templates/{template_id}/duplicate')
def duplicate_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(OutreachTemplate).filter(OutreachTemplate.id == template_id).first()
    if not t:
        return {'error': 'Template not found'}
    copy = OutreachTemplate(
        name=f"{t.name} (Copy)",
        subject=t.subject,
        body=t.body,
        category=t.category,
        is_default=False
    )
    db.add(copy)
    db.commit()
    db.refresh(copy)
    return {'id': copy.id, 'name': copy.name, 'subject': copy.subject, 'body': copy.body,
            'category': copy.category, 'is_default': copy.is_default,
            'created_at': str(copy.created_at), 'updated_at': str(copy.updated_at)}


@router.post('/templates/{template_id}/set_default')
def set_default_template(template_id: int, db: Session = Depends(get_db)):
    t = db.query(OutreachTemplate).filter(OutreachTemplate.id == template_id).first()
    if not t:
        return {'error': 'Template not found'}
    settings = db.query(AgentSettings).first()
    if not settings:
        settings = AgentSettings()
        db.add(settings)
    settings.default_outreach_template_id = template_id
    db.commit()
    return {'default_template_id': template_id, 'name': t.name}


@router.get('/emails/{lead_id}')
def get_emails(lead_id: int, db: Session = Depends(get_db)):
    settings = db.query(AgentSettings).first()
    default_sig_id = settings.default_template_id if settings else None

    emails = db.query(Email).filter(Email.lead_id == lead_id).order_by(Email.sent_at.desc()).all()
    result = []
    for e in emails:
        sig_id = e.signature_template_id or default_sig_id
        sig = db.query(SignatureTemplate).filter(SignatureTemplate.id == sig_id).first() if sig_id else None

        result.append({
            'id': e.id,
            'subject': e.subject,
            'body': e.body,
            'html_body': e.html_body,
            'header_image_url': e.header_image_url,
            'signature_template_id': sig_id,
            'status': e.status,
            'to_email': e.to_email,
            'sent_at': str(e.sent_at),
            'opened_at': str(e.opened_at) if e.opened_at else None,
            'gmail_message_id': e.gmail_message_id,
            'error_message': e.error_message,
            'outreach_template_id': e.outreach_template_id,
            'outreach_template_name': e.outreach_template_name,
        })
    return result


class SendEmailRequest(BaseModel):
    subject: Optional[str] = None
    body: Optional[str] = None
    html_body: Optional[str] = None
    header_image_url: Optional[str] = None
    signature_template_id: Optional[int] = None
    full_name: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    company: Optional[str] = None
    sender_email: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    linkedin: Optional[str] = None
    address: Optional[str] = None
    logo_url: Optional[str] = None
    digital_signature_url: Optional[str] = None
    footer_banner_url: Optional[str] = None

from .formatting import generate_professional_html

@router.post('/send/{email_id}')
def send_email(email_id: int, req: Optional[SendEmailRequest] = None, db: Session = Depends(get_db)):
    from apps.api.core.gmail_provider import send_email_via_gmail
    from datetime import datetime, timezone
    import logging
    
    logger = logging.getLogger(__name__)

    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        return {'error': 'Email not found'}
        
    if email.status == 'sent':
        return {'status': 'sent', 'email_id': email_id, 'to': email.to_email, 'gmail_message_id': email.gmail_message_id}
        
    if req:
        if req.subject is not None:
            email.subject = req.subject
        if req.body is not None:
            email.body = req.body
        if req.header_image_url is not None:
            email.header_image_url = req.header_image_url if req.header_image_url != '' else None
        if req.signature_template_id is not None:
            email.signature_template_id = req.signature_template_id if req.signature_template_id != 0 else None
            
        for f in ['full_name', 'designation', 'department', 'company', 'sender_email', 'phone', 'website', 'linkedin', 'address', 'logo_url', 'digital_signature_url', 'footer_banner_url']:
            if getattr(req, f) is not None:
                val = getattr(req, f)
                setattr(email, f, val if val != '' else None)
            
    signature_data = email
    from apps.api.modules.crm.models import AgentSettings
    settings = db.query(AgentSettings).first()
    default_sig_id = settings.default_template_id if settings else None

    sig_id = email.signature_template_id or default_sig_id
    if sig_id:
        sig_template = db.query(SignatureTemplate).filter(SignatureTemplate.id == sig_id).first()
        if sig_template:
            class MergedSignature:
                def __getattr__(self, name):
                    val = getattr(email, name, None)
                    if not val:
                        if name == 'sender_email':
                            return getattr(sig_template, 'email', None)
                        elif name == 'header_image_url':
                            return getattr(sig_template, 'header_banner_url', None)
                        elif hasattr(sig_template, name):
                            return getattr(sig_template, name)
                    return val
            signature_data = MergedSignature()

    # Auto-generate HTML from the body, header, and the draft email's own override fields
    email.html_body, inline_images = generate_professional_html(email.body, email.subject, getattr(signature_data, 'header_image_url', None), signature_data)
    db.commit()

    logger.info("Sending email...")
    logger.info(f"Recipient: {email.to_email}")
    logger.info(f"Subject: {email.subject}")

    try:
        # Call Gmail API
        msg_id = send_email_via_gmail(email.to_email, email.subject, email.body, email.html_body, inline_images)
        
        email.status = 'sent'
        email.sent_at = datetime.now(timezone.utc)
        email.gmail_message_id = msg_id
        email.error_message = None
        db.commit()
        
        logger.info(f"HTTP Status: 200 OK")
        logger.info(f"Gmail Message ID: {msg_id}")
        logger.info(f"Response Body: Successfully sent to {email.to_email}")
        
        return {'status': 'sent', 'email_id': email_id, 'to': email.to_email, 'gmail_message_id': msg_id}
        
    except Exception as e:
        error_str = str(e)
        email.status = 'failed'
        email.error_message = error_str
        db.commit()
        
        logger.error(f"HTTP Status: Error")
        logger.error(f"Gmail Message ID: N/A")
        logger.error(f"Response Body: {error_str}")
        
        return {'status': 'failed', 'email_id': email_id, 'to': email.to_email, 'error': error_str}


@router.get('/campaigns')
def list_campaigns(db: Session = Depends(get_db)):
    campaigns = db.query(Campaign).order_by(Campaign.created_at.desc()).all()
    result = []
    for c in campaigns:
        emails_in_campaign = (
            db.query(Email)
            .join(Lead, Email.lead_id == Lead.id)
            .filter(Lead.campaign_id == c.id)
            .all()
        )
        sent = sum(1 for e in emails_in_campaign if e.status == 'sent')
        replied = sum(1 for e in emails_in_campaign if e.replied_at)
        result.append({
            'id': c.id,
            'name': c.name,
            'status': c.status,
            'created_at': str(c.created_at),
            'emails_sent': sent,
            'replies': replied,
        })
    return result


class EmailEditRequest(BaseModel):
    subject: str | None = None
    body: str | None = None
    header_image_url: str | None = None
    signature_template_id: int | None = None
    full_name: str | None = None
    designation: str | None = None
    department: str | None = None
    company: str | None = None
    sender_email: str | None = None
    phone: str | None = None
    website: str | None = None
    linkedin: str | None = None
    address: str | None = None
    logo_url: str | None = None
    digital_signature_url: str | None = None
    footer_banner_url: str | None = None


@router.patch('/emails/{email_id}')
def edit_email(email_id: int, req: EmailEditRequest, db: Session = Depends(get_db)):
    """Edit an email's subject and/or body before sending."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if not email:
        return {'error': 'Email not found'}
    if email.status == 'sent':
        return {'error': 'Cannot edit an already-sent email'}
        
    update_data = req.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(email, key, value)
        
    from .formatting import format_and_save_email_html
    format_and_save_email_html(db, email)
        
    db.commit()
    return {'id': email_id, 'subject': email.subject, 'body': email.body, 'status': email.status, 'html_body': email.html_body}
