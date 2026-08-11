from sqlalchemy.orm import Session
from fastapi import HTTPException
from .repository import CRMRepository
from .schemas import CompanyCreate, ContactCreate, LeadCreate


class CRMService:
    def __init__(self):
        self.repo = CRMRepository()

    def upsert_company(self, db: Session, company_data: CompanyCreate):
        company = self.repo.upsert_company(db, company_data)
        db.commit()
        db.refresh(company)
        return company

    def upsert_contact(self, db: Session, contact_data: ContactCreate):
        contact = self.repo.upsert_contact(db, contact_data)
        db.commit()
        db.refresh(contact)
        return contact

    def create_lead(self, db: Session, lead_data: LeadCreate):
        from .models import Contact
        contact = db.query(Contact).filter(Contact.email == lead_data.contact_email).first()
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")
        
        lead = self.repo.create_lead(db, contact.id, lead_data.status)
        db.commit()
        db.refresh(lead)
        return lead

    def get_lead(self, db: Session, lead_id: int):
        lead = self.repo.get_lead(db, lead_id)
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")
        return lead

    def get_lead_timeline(self, db: Session, lead_id: int):
        lead = self.get_lead(db, lead_id)
        activities = self.repo.get_lead_activities(db, lead_id)
        return {"lead": lead, "activities": activities}

    def list_leads(self, db: Session, status: str | None = None, skip: int = 0, limit: int = 100):
        leads, total = self.repo.list_leads(db, status=status, skip=skip, limit=limit)
        return {"leads": leads, "total": total}

    def list_campaigns(self, db: Session, skip: int = 0, limit: int = 100):
        campaigns, total = self.repo.list_campaigns(db, skip=skip, limit=limit)
        return {"campaigns": campaigns, "total": total}
