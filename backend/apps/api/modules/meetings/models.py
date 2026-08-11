from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, Text
from apps.api.db.database import Base
from datetime import datetime, timezone

def utcnow():
    return datetime.now(timezone.utc)

class GoogleOAuthCredential(Base):
    __tablename__ = 'google_oauth_credentials'
    __table_args__ = {'extend_existing': True}
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), index=True)
    email = Column(String, unique=True, index=True)
    access_token = Column(Text, nullable=False)
    refresh_token = Column(Text)
    token_uri = Column(String)
    client_id = Column(String)
    client_secret = Column(String)
    scopes = Column(Text)
    expiry = Column(DateTime)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
