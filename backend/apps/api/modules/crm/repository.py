from sqlalchemy.orm import Session
from .models import Company, Contact, Lead, Activity, Campaign
from .schemas import CompanyCreate, ContactCreate, LeadCreate


class CRMRepository:
    def upsert_company(self, db: Session, company_data: CompanyCreate) -> Company:
        company = db.query(Company).filter(Company.domain == company_data.domain).first()
        if company:
            company.name = company_data.name
        else:
            company = Company(name=company_data.name, domain=company_data.domain)
            db.add(company)
        db.flush()
        return company

    def upsert_contact(self, db: Session, contact_data: ContactCreate) -> Contact:
        contact = db.query(Contact).filter(Contact.email == contact_data.email).first()
        company_id = None
        if contact_data.company_domain:
            company = db.query(Company).filter(Company.domain == contact_data.company_domain).first()
            if company:
                company_id = company.id
        
        if contact:
            contact.first_name = contact_data.first_name
            contact.last_name = contact_data.last_name
            if contact_data.linkedin_url:
                contact.linkedin_url = contact_data.linkedin_url
            if company_id:
                contact.company_id = company_id
        else:
            contact = Contact(
                first_name=contact_data.first_name,
                last_name=contact_data.last_name,
                email=contact_data.email,
                linkedin_url=contact_data.linkedin_url,
                company_id=company_id
            )
            db.add(contact)
        db.flush()
        return contact

    def create_lead(self, db: Session, contact_id: int, status: str = "new") -> Lead:
        lead = Lead(contact_id=contact_id, status=status)
        db.add(lead)
        db.flush()
        
        # Create immutable timeline event
        activity = Activity(
            lead_id=lead.id,
            type="Lead Created",
            description=f"Lead created with status {status}"
        )
        db.add(activity)
        db.flush()
        
        return lead

    def get_lead(self, db: Session, lead_id: int) -> Lead:
        return db.query(Lead).filter(Lead.id == lead_id).first()

    def get_lead_activities(self, db: Session, lead_id: int):
        return db.query(Activity).filter(Activity.lead_id == lead_id).order_by(Activity.created_at.desc()).all()

    def list_leads(self, db: Session, status: str | None = None, skip: int = 0, limit: int = 100):
        query = db.query(Lead, Contact, Company).outerjoin(Contact, Lead.contact_id == Contact.id).outerjoin(Company, Contact.company_id == Company.id)
        if status:
            query = query.filter(Lead.status == status)
        total = query.count()
        results = query.order_by(Lead.created_at.desc()).offset(skip).limit(limit).all()

        leads = []
        for lead, contact, company in results:
            # Build a plain dict so Pydantic can serialize company_name/contact_name
            # (dynamically set attributes on SQLAlchemy ORM objects are invisible
            # to Pydantic's from_attributes serializer — dicts always work).
            leads.append({
                "id": lead.id,
                "contact_id": lead.contact_id,
                "status": lead.status,
                "deal_value": lead.deal_value,
                "lead_score": lead.lead_score,
                "priority": lead.priority,
                "campaign_id": lead.campaign_id,
                "stage_entered_at": lead.stage_entered_at,
                "last_activity_at": lead.last_activity_at,
                "created_at": lead.created_at,
                "updated_at": lead.updated_at,
                "company_name": company.name if company else None,
                "contact_name": (
                    f"{contact.first_name or ''} {contact.last_name or ''}".strip()
                    if contact else None
                ),
            })

        return leads, total

    def list_campaigns(self, db: Session, skip: int = 0, limit: int = 100):
        query = db.query(Campaign)
        total = query.count()
        campaigns = query.order_by(Campaign.created_at.desc()).offset(skip).limit(limit).all()
        return campaigns, total
