import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apps.api.db.database import Base
from apps.api.modules.email.service import EmailService
from apps.api.modules.crm.models import Contact, Lead, Activity, Email, Reply

engine = create_engine("sqlite:///:memory:")
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)

@patch('apps.api.modules.email.service.build')
@patch('apps.api.core.google_auth.get_google_credentials')
def test_send_email_gmail(mock_get_creds, mock_build, db_session):
    mock_get_creds.return_value = MagicMock()
    
    mock_service = MagicMock()
    mock_build.return_value = mock_service
    
    contact = Contact(email="test@example.com", first_name="Test")
    db_session.add(contact)
    db_session.flush()
    
    lead = Lead(contact_id=contact.id, status="NEW")
    db_session.add(lead)
    db_session.commit()
    
    email_service = EmailService(db_session)
    email_record = email_service.send_email(
        to="test@example.com",
        subject="Test Subject",
        body="Hello World",
        from_email="me@example.com",
        lead_id=lead.id
    )
    
    assert email_record.id is not None
    assert email_record.status == "sent"
    
    mock_service.users().messages().send.assert_called_once()
    
    activity = db_session.query(Activity).filter(Activity.lead_id == lead.id).first()
    assert activity is not None
    assert activity.type == "Email Sent"

@patch('apps.api.modules.email.service.smtplib.SMTP')
@patch('apps.api.core.google_auth.get_google_credentials')
def test_send_email_smtp_fallback(mock_get_creds, mock_smtp, db_session):
    # Make get_google_credentials return None to trigger SMTP fallback
    mock_get_creds.return_value = None
    
    with patch('apps.api.modules.email.service.settings') as mock_settings:
        mock_settings.SMTP_HOST = 'smtp.test.com'
        mock_settings.SMTP_PORT = 587
        
        email_service = EmailService(db_session)
        email_record = email_service.send_email(
            to="test@example.com",
            subject="Test Subject",
            body="Hello World",
            from_email="me@example.com",
            lead_id=None
        )
        
        assert email_record.id is not None
        assert email_record.status == "sent"
        
        mock_smtp.assert_called_once()
