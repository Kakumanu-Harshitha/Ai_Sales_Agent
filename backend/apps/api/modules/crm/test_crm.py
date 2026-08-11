import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apps.api.db.database import Base
from apps.api.modules.crm.schemas import CompanyCreate, ContactCreate, LeadCreate
from apps.api.modules.crm.repository import CRMRepository
from apps.api.modules.crm.service import CRMService
from apps.api.modules.crm.models import Activity

# Setup in-memory SQLite for testing
engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def service():
    return CRMService()

def test_upsert_company(db_session, service):
    company_data = CompanyCreate(name="Acme Corp", domain="acme.com")
    company = service.upsert_company(db_session, company_data)
    
    assert company.id is not None
    assert company.name == "Acme Corp"
    assert company.domain == "acme.com"
    
    # Upsert with different name but same domain
    updated_data = CompanyCreate(name="Acme Corporation", domain="acme.com")
    updated_company = service.upsert_company(db_session, updated_data)
    
    assert updated_company.id == company.id
    assert updated_company.name == "Acme Corporation"

def test_upsert_contact(db_session, service):
    company_data = CompanyCreate(name="Acme Corp", domain="acme.com")
    service.upsert_company(db_session, company_data)
    
    contact_data = ContactCreate(
        first_name="John", 
        last_name="Doe", 
        email="john@acme.com", 
        company_domain="acme.com"
    )
    contact = service.upsert_contact(db_session, contact_data)
    
    assert contact.id is not None
    assert contact.first_name == "John"
    assert contact.company_id is not None

def test_create_lead_and_timeline(db_session, service):
    contact_data = ContactCreate(first_name="Jane", last_name="Smith", email="jane@test.com")
    service.upsert_contact(db_session, contact_data)
    
    lead_data = LeadCreate(contact_email="jane@test.com", status="NEW")
    lead = service.create_lead(db_session, lead_data)
    
    assert lead.id is not None
    assert lead.status == "NEW"
    
    # Check timeline event
    timeline = service.get_lead_timeline(db_session, lead.id)
    assert len(timeline["activities"]) == 1
    assert timeline["activities"][0].type == "Lead Created"
