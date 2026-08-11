from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.db.database import get_db
from .schemas import SendEmailRequest, EmailResponse, ReplyResponse
from .service import EmailService

router = APIRouter(prefix="/email", tags=["Email"])

@router.post("/send", response_model=EmailResponse)
def send_email(request: SendEmailRequest, db: Session = Depends(get_db)):
    service = EmailService(db)
    email = service.send_email(
        to=request.to, 
        subject=request.subject, 
        body=request.body, 
        from_email=request.from_email,
        lead_id=request.lead_id
    )
    db.commit()
    db.refresh(email)
    return email

@router.get("/replies/unprocessed", response_model=list[ReplyResponse])
def get_unprocessed_replies(db: Session = Depends(get_db)):
    service = EmailService(db)
    return service.get_unprocessed_replies()

@router.post("/replies/{reply_id}/process", response_model=ReplyResponse)
def process_reply(reply_id: int, db: Session = Depends(get_db)):
    service = EmailService(db)
    reply = service.mark_reply_processed(reply_id)
    db.commit()
    db.refresh(reply)
    return reply
