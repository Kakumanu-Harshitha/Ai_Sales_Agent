from fastapi import FastAPI, Depends, Query
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from .core.config import settings
from .db.database import engine, Base, get_db

# Import models to ensure they are registered with Base
from .modules.crm import models as crm_models
from .modules.meetings import models as meetings_models
from .core.idempotency import IdempotencyRecord  # Register idempotency table
from .modules.prospecting import models as prospecting_models  # Register ProspectingJob table
from .modules.intelligence import models as intelligence_models  # Register Company Intelligence tables
from .modules.orchestration import agent_models as agent_models  # Register AgentGoal, AgentDecision, AgentReflection
from .modules.knowledge import models as knowledge_models  # Register SETV Knowledge tables

# Create tables (in production, use Alembic)
Base.metadata.create_all(bind=engine)

from .core.scheduler import start_scheduler, stop_scheduler
import logging
from logging.handlers import RotatingFileHandler
import os

os.makedirs("logs", exist_ok=True)
_file_handler = RotatingFileHandler(os.path.join("logs", "agent.log"), maxBytes=1024*1024*5, backupCount=2)
_file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
_file_handler.setLevel(logging.INFO)

# Uvicorn already configures the root logger, but we can add our file handler to it
logging.getLogger().addHandler(_file_handler)
logging.getLogger().setLevel(logging.INFO)

def _auto_seed_outreach_templates():
    """Seed the 6 default outreach templates if they haven't been seeded yet."""
    try:
        from .db.database import SessionLocal
        from .modules.crm.models import OutreachTemplate
        from datetime import datetime
        db = SessionLocal()
        try:
            count = db.query(OutreachTemplate).filter(OutreachTemplate.is_default == True).count()
            if count >= 6:
                return
            from .modules.outreach.seed_templates import DEFAULT_TEMPLATES
            for t in DEFAULT_TEMPLATES:
                exists = db.query(OutreachTemplate).filter(OutreachTemplate.name == t["name"]).first()
                if not exists:
                    db.add(OutreachTemplate(**t))
            db.commit()
        finally:
            db.close()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"Auto-seed outreach templates skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _auto_seed_outreach_templates()

    # ── Inline schema migrations ──────────────────────────────────────────────
    # SQLAlchemy's create_all() creates missing TABLES but never adds columns
    # to existing tables. Add any new columns here with IF NOT EXISTS so this
    # is fully idempotent (safe to run on every restart).
    from .db.database import engine
    _MIGRATIONS = [
        # Enhancement: outreach strategy on agent_goals
        "ALTER TABLE agent_goals ADD COLUMN IF NOT EXISTS outreach_strategy VARCHAR DEFAULT 'fixed'",
    ]
    try:
        with engine.connect() as conn:
            for sql in _MIGRATIONS:
                conn.execute(__import__('sqlalchemy').text(sql))
            conn.commit()
    except Exception as _mig_exc:
        import logging as _lg
        _lg.getLogger(__name__).warning("Schema migration warning (may be harmless): %s", _mig_exc)

    # Clear any ghost "Running" statuses from previous crashes or hot-reloads
    from .db.database import SessionLocal
    from .modules.crm.models import AgentSettings
    
    db = SessionLocal()
    try:
        settings_record = db.query(AgentSettings).first()
        if settings_record and settings_record.current_status == "Running":
            settings_record.current_status = "Idle"
            db.commit()
    finally:
        db.close()

    start_scheduler()
    yield
    stop_scheduler()



app = FastAPI(title="SETV AI Sales Agent API", lifespan=lifespan)

# CORS middleware for React dashboard
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.staticfiles import StaticFiles
import os

os.makedirs(os.path.join("static", "uploads"), exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Include routers ───────────────────────────────────────────────────────────
from .modules.crm.router import router as crm_router
from .modules.meetings.router import router as meetings_router
from .modules.email.router import router as email_router
from .modules.pipeline.router import router as pipeline_router
from .modules.orchestration.router import router as orchestration_router
from .modules.prospecting.router import router as prospecting_router
from .modules.signals.router import router as signals_router
from .modules.outreach.router import router as outreach_router
from .modules.replies.router import router as replies_router
from .modules.intelligence.router import router as intelligence_router
from .modules.agents_status.router import router as agents_router
from .modules.knowledge.router import router as knowledge_router

app.include_router(crm_router)
app.include_router(meetings_router)
app.include_router(email_router)
app.include_router(pipeline_router)
app.include_router(orchestration_router)
app.include_router(prospecting_router)
app.include_router(signals_router)
app.include_router(outreach_router)
app.include_router(replies_router)
app.include_router(agents_router)
app.include_router(intelligence_router)
app.include_router(knowledge_router)


# ── Top-level convenience routes ─────────────────────────────────────────────
# /pipeline/report is handled by pipeline_router.
# The rest are convenience aliases that delegate to the CRM/meetings services.

from .modules.crm.service import CRMService
from .modules.crm.schemas import LeadListResponse, CampaignListResponse
from .modules.meetings.schemas import MeetingListResponse
from .modules.crm.models import Meeting as MeetingModel

_crm_service = CRMService()


@app.get("/leads", response_model=LeadListResponse, tags=["Top-Level"])
def get_leads(
    status: str | None = Query(None),
    search: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all leads with optional status and search filters."""
    return _crm_service.list_leads(db, status=status, skip=skip, limit=limit)


@app.get("/campaigns", response_model=CampaignListResponse, tags=["Top-Level"])
def get_campaigns(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all campaigns."""
    return _crm_service.list_campaigns(db, skip=skip, limit=limit)


@app.get("/meetings", response_model=MeetingListResponse, tags=["Top-Level"])
def get_meetings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all meetings."""
    query = db.query(MeetingModel)
    total = query.count()
    meetings = query.order_by(MeetingModel.scheduled_at.desc().nullslast()).offset(skip).limit(limit).all()
    return {"meetings": meetings, "total": total}


@app.get("/health")
def health_check():
    return {"status": "ok", "environment": settings.ENVIRONMENT}
