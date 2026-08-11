import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from apps.api.db.database import Base
from apps.api.modules.meetings.models import GoogleOAuthCredential
from apps.api.modules.crm.models import Contact, Lead, Activity, User
from apps.api.modules.meetings.service import MeetingsService

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
    return MeetingsService()

@patch('apps.api.modules.meetings.service.build')
@patch('apps.api.modules.meetings.service.Credentials')
def test_book_meeting(mock_credentials, mock_build, db_session, service):
    user = User(email="user@example.com", name="User")
    db_session.add(user)
    db_session.flush()
    
    cred = GoogleOAuthCredential(
        user_id=user.id,
        email="test@gmail.com",
        access_token="fake_token",
        client_id="fake_client",
        client_secret="fake_secret"
    )
    db_session.add(cred)
    
    contact = Contact(email="contact@example.com", first_name="Contact")
    db_session.add(contact)
    db_session.flush()
    
    lead = Lead(contact_id=contact.id, status="NEW")
    db_session.add(lead)
    db_session.commit()
    
    mock_events = MagicMock()
    mock_events.insert.return_value.execute.return_value = {
        'id': 'fake_event_id',
        'conferenceData': {
            'entryPoints': [{'entryPointType': 'video', 'uri': 'https://meet.google.com/abc-defg-hij'}]
        }
    }
    mock_service = MagicMock()
    mock_service.events.return_value = mock_events
    mock_build.return_value = mock_service
    
    start_time = datetime.now(timezone.utc)
    end_time = start_time + timedelta(hours=1)
    
    result = service.book_meeting(
        db=db_session,
        account_id=user.id,
        contact_id=contact.id,
        contact_email="contact@example.com",
        slot_start=start_time,
        slot_end=end_time,
        title="Intro Call",
        description="Discussing the product"
    )
    
    assert result['status'] == 'success'
    assert result['meeting_link'] == 'https://meet.google.com/abc-defg-hij'
    assert result['event_id'] == 'fake_event_id'
    
    activity = db_session.query(Activity).filter(Activity.lead_id == lead.id).first()
    assert activity is not None
    assert activity.type == "Meeting Scheduled"
    assert "https://meet.google.com/abc-defg-hij" in activity.description
