from sqlalchemy.orm import Session
from .models import GoogleOAuthCredential

class MeetingsRepository:
    def get_credential(self, db: Session, account_id: int):
        return db.query(GoogleOAuthCredential).filter(GoogleOAuthCredential.user_id == account_id).first()
    
    def save_credential(self, db: Session, cred_data: dict):
        cred = db.query(GoogleOAuthCredential).filter(GoogleOAuthCredential.user_id == cred_data['user_id']).first()
        if cred:
            for key, value in cred_data.items():
                setattr(cred, key, value)
        else:
            cred = GoogleOAuthCredential(**cred_data)
            db.add(cred)
        db.flush()
        return cred
