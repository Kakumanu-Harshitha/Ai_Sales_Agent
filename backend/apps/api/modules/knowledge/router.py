from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from apps.api.db.database import get_db
from .models import KnowledgeBase, KnowledgeSyncLog
from .service import KnowledgeSyncService
import os

router = APIRouter(prefix="/knowledge", tags=["Knowledge"])

@router.get("/current")
def get_current_knowledge(db: Session = Depends(get_db)):
    """Returns the most recent knowledge base version."""
    kb = db.query(KnowledgeBase).order_by(KnowledgeBase.version.desc()).first()
    if not kb:
        return {"version": 0, "data": None, "last_updated": None}
    
    return {
        "version": kb.version,
        "data": kb.data,
        "last_updated": kb.created_at
    }

@router.get("/logs")
def get_sync_logs(limit: int = 10, db: Session = Depends(get_db)):
    """Returns the history of synchronization runs."""
    logs = db.query(KnowledgeSyncLog).order_by(KnowledgeSyncLog.sync_time.desc()).limit(limit).all()
    return logs

def run_sync_task(db: Session, base_url: str):
    service = KnowledgeSyncService(db, base_url=base_url)
    service.sync()

@router.post("/sync")
def trigger_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Manually triggers a synchronization task in the background."""
    # Check if currently running to avoid overlapping syncs
    running = db.query(KnowledgeSyncLog).filter(KnowledgeSyncLog.status == "running").first()
    if running:
        raise HTTPException(status_code=400, detail="A synchronization is already in progress.")
        
    base_url = os.getenv("SETV_OFFICIAL_URL", "https://www.setvglobal.com/")
    
    # We pass a new session to the background task usually, or since FastAPI Depends(get_db) 
    # yields a session that closes after request, it's safer to spawn a new one inside the background task.
    # To be perfectly safe, we'll import SessionLocal.
    
    from apps.api.db.database import SessionLocal
    
    def background_job():
        db_session = SessionLocal()
        try:
            run_sync_task(db_session, base_url)
        finally:
            db_session.close()

    background_tasks.add_task(background_job)
    
    return {"message": "Knowledge sync triggered in background.", "status": "running"}
