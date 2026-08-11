"""
Centralized APScheduler setup for Auto Agent mode.
Runs a single orchestrator job every minute that checks AgentSettings.
"""

import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apps.api.core.config import settings

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None

def auto_agent_job():
    """Runs the goal-directed AgentController cycle (replaces AutoAgentRunner)."""
    try:
        from apps.api.modules.orchestration.agent_controller import AgentController
        AgentController().run_cycle()
    except Exception as e:
        logger.error(f"Auto agent job error: {e}", exc_info=True)


def start_scheduler():
    """Start the APScheduler with the single Auto Agent job."""
    global _scheduler
    if _scheduler is not None:
        logger.warning("Scheduler already running, skipping duplicate start.")
        return

    tz = getattr(settings, "APSCHEDULER_TIMEZONE", "UTC") or "UTC"

    _scheduler = BackgroundScheduler(timezone=tz)

    _scheduler.add_job(
        auto_agent_job,
        "interval",
        minutes=1,
        id="auto_agent_job",
        name="Auto Agent Orchestrator",
        replace_existing=True,
    )

    def run_knowledge_sync():
        try:
            from apps.api.modules.knowledge.service import KnowledgeSyncService
            from apps.api.db.database import SessionLocal
            import os
            
            db = SessionLocal()
            try:
                base_url = os.getenv("SETV_OFFICIAL_URL", "https://www.setvglobal.com/")
                KnowledgeSyncService(db, base_url).sync()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Knowledge sync job error: {e}", exc_info=True)

    _scheduler.add_job(
        run_knowledge_sync,
        "interval",
        hours=24,
        id="knowledge_sync_job",
        name="SETV Knowledge Sync",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("APScheduler started with Auto Agent (1min) and Knowledge Sync (24h).")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("APScheduler stopped.")
