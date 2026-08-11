"""
Orchestration module — routes for running the full AI pipeline.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.db.database import get_db
from .schemas import (
    RunProspectingRequest, RunProspectingResponse,
    ProcessRepliesRequest, ProcessRepliesResponse,
)
from .service import OrchestrationService
from .reply_handler import ReplyHandlerService

router = APIRouter(prefix="/orchestration", tags=["Orchestration"])

_orch_service = OrchestrationService()
_reply_handler = ReplyHandlerService()


@router.post("/run-prospecting", response_model=RunProspectingResponse)
def run_prospecting(request: RunProspectingRequest, db: Session = Depends(get_db)):
    """
    Full AI pipeline: Prospect → Signal Detect → Outreach.

    1. Calls the Prospecting Agent (Gemini + Google Search) to discover leads
    2. Runs Signal Detection on each discovered lead
    3. Generates outreach for leads above the score threshold
    """
    return _orch_service.run_prospecting_pipeline(db, request)


@router.post("/process-replies", response_model=ProcessRepliesResponse)
def process_replies(request: ProcessRepliesRequest = ProcessRepliesRequest(), db: Session = Depends(get_db)):
    """
    Reply processing pipeline: Classify → Route → Book/Close.

    1. Fetches unprocessed replies
    2. Classifies intent/sentiment with the Reply Handling Agent
    3. Auto-books meetings for Demo/Meeting Requests
    4. Marks leads as closed_lost for Not Interested
    """
    return _reply_handler.process_replies_pipeline(db, request)

from apps.api.modules.crm.models import AgentSettings, JobTemplate
from apps.api.modules.prospecting.models import ProspectingJob
import json

@router.get('/settings')
def get_settings(db: Session = Depends(get_db)):
    settings = db.query(AgentSettings).first()
    if not settings:
        settings = AgentSettings()
        db.add(settings)
        db.commit()
    
    return {
        "enabled": settings.enabled,
        "interval_minutes": settings.interval_minutes,
        "default_template_id": settings.default_template_id,
        "auto_send_emails": settings.auto_send_emails,
        "max_leads_per_run": settings.max_leads_per_run,
        "max_outreach_per_cycle": getattr(settings, 'max_outreach_per_cycle', 3),
        "daily_email_limit": settings.daily_email_limit,
        "reply_monitoring": settings.reply_monitoring,
        "last_run": settings.last_run,
        "next_run": settings.next_run,
        "current_status": settings.current_status,
        "current_stage": settings.current_stage
    }

@router.post('/settings')
def update_settings(data: dict, db: Session = Depends(get_db)):
    settings = db.query(AgentSettings).first()
    if not settings:
        settings = AgentSettings()
        db.add(settings)
    
    for key, value in data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    
    db.commit()
    return {"status": "success"}

@router.get('/templates')
def list_templates(db: Session = Depends(get_db)):
    templates = db.query(JobTemplate).order_by(JobTemplate.created_at.desc()).all()
    return [
        {
            "id": t.id,
            "name": t.name,
            "regions": t.regions,
            "company_size_min": t.company_size_min,
            "company_size_max": t.company_size_max,
            "industries": t.industries,
            "target_roles": t.target_roles,
            "keywords": t.keywords,
            "technologies": t.technologies,
            "max_results": t.max_results
        } for t in templates
    ]

@router.post('/templates')
def create_template(data: dict, db: Session = Depends(get_db)):
    template = JobTemplate(
        name=data.get('name'),
        regions=data.get('regions'),
        company_size_min=data.get('company_size_min'),
        company_size_max=data.get('company_size_max'),
        industries=data.get('industries'),
        target_roles=data.get('target_roles'),
        keywords=data.get('keywords'),
        technologies=data.get('technologies'),
        max_results=data.get('max_results', 15)
    )
    db.add(template)
    db.commit()
    return {"status": "success", "id": template.id}
@router.get('/agent/logs')
def get_agent_logs(limit: int = 100):
    """Return tail of agent.log for developer tools"""
    try:
        import os
        log_path = os.path.join("logs", "agent.log")
        if not os.path.exists(log_path):
            return {"logs": ["No logs available yet. Start the agent to begin tracking."]}
        
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        return {"logs": [line.strip() for line in lines[-limit:]]}
    except Exception as e:
        return {"logs": [f"Error reading logs: {e}"]}


@router.get('/jobs')
def list_jobs(limit: int = 10, db: Session = Depends(get_db)):
    jobs = db.query(ProspectingJob).order_by(ProspectingJob.id.desc()).limit(limit).all()
    result = []
    for j in jobs:
        # Load logs if available
        logs = []
        if j.execution_logs:
            try:
                logs = json.loads(j.execution_logs)
            except:
                pass
        
        result.append({
            "id": j.id,
            "start_time": j.started_at or j.created_at,
            "end_time": j.completed_at,
            "status": j.status,
            "template_used_id": j.template_used_id,
            "companies_discovered": j.total_companies_discovered,
            "leads_found": j.total_leads_persisted,
            "contacts_verified": j.total_leads_qualified,
            "outreach_generated": j.outreach_generated,
            "emails_sent": j.emails_sent,
            "errors": j.error_message,
            "logs": logs
        })
    return result


# ── Agent Controller endpoints (new — additive only) ─────────────────────────
from apps.api.modules.orchestration.agent_models import AgentGoal, AgentDecision, AgentReflection
from apps.api.modules.orchestration.agent_controller import AgentController

_agent_controller = AgentController()


@router.get('/agent/goal')
def get_agent_goal(db: Session = Depends(get_db)):
    """Return current AgentGoal configuration with live current_value."""
    from datetime import datetime, timedelta
    goal = db.query(AgentGoal).first()
    if not goal:
        goal = AgentGoal()
        db.add(goal)
        db.commit()
        db.refresh(goal)

    # Compute live current_value using same logic as perceive()
    now = datetime.utcnow()
    if goal.period == "daily":
        period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        days_since_monday = now.weekday()
        period_start = (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    from apps.api.modules.orchestration.agent_controller import AgentController
    current_value = _agent_controller._measure_goal_progress(db, goal.target_metric, period_start)

    return {
        "id": goal.id,
        "target_metric": goal.target_metric,
        "target_value": goal.target_value,
        "current_value": current_value,
        "period": goal.period,
        "min_sample_for_revision": goal.min_sample_for_revision,
        "reply_rate_floor": goal.reply_rate_floor,
        "reflect_every_n_cycles": goal.reflect_every_n_cycles,
        "auto_rescan_signals": goal.auto_rescan_signals,
        "auto_re_enrich_lead": goal.auto_re_enrich_lead,
        "auto_revise_template": goal.auto_revise_template,
        "auto_book_meeting": goal.auto_book_meeting,
        "outreach_strategy": getattr(goal, 'outreach_strategy', 'fixed'),
        "updated_at": goal.updated_at,
    }


@router.post('/agent/goal')
def update_agent_goal(data: dict, db: Session = Depends(get_db)):
    """Upsert AgentGoal configuration."""
    goal = db.query(AgentGoal).first()
    if not goal:
        goal = AgentGoal()
        db.add(goal)

    allowed_fields = {
        "target_metric", "target_value", "period",
        "min_sample_for_revision", "reply_rate_floor", "reflect_every_n_cycles",
        "auto_rescan_signals", "auto_re_enrich_lead", "auto_revise_template", "auto_book_meeting",
        "outreach_strategy",
    }
    for key, value in data.items():
        if key in allowed_fields and hasattr(goal, key):
            setattr(goal, key, value)

    db.commit()
    return {"status": "success"}


@router.get('/agent/decisions')
def list_agent_decisions(limit: int = 20, db: Session = Depends(get_db)):
    """
    Return the last N AgentDecision rows.
    This is the demoable 'why did the agent do X' view.
    """
    decisions = (
        db.query(AgentDecision)
        .order_by(AgentDecision.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for d in decisions:
        try:
            state_snap = json.loads(d.state_snapshot or "{}")
        except Exception:
            state_snap = {}
        try:
            outcome = json.loads(d.outcome or "{}")
        except Exception:
            outcome = {}
        try:
            params = json.loads(d.action_params or "{}")
        except Exception:
            params = {}

        result.append({
            "id": d.id,
            "cycle_id": d.cycle_id,
            "chosen_action": d.chosen_action,
            "action_params": params,
            "reasoning": d.reasoning,
            "status": d.status,
            "outcome": outcome,
            "error_detail": d.error_detail,
            "goal_progress": state_snap.get("goal_progress"),
            "created_at": d.created_at,
            "executed_at": d.executed_at,
        })
    return result


@router.post('/agent/decisions/{decision_id}/approve')
def approve_agent_decision(decision_id: int, db: Session = Depends(get_db)):
    """
    Approve and execute a pending_approval decision.
    This is the human-approval gate for risky actions.
    """
    result = _agent_controller.execute_pending_decision(db, decision_id)
    return result


@router.get('/agent/reflections')
def list_agent_reflections(limit: int = 10, db: Session = Depends(get_db)):
    """Return the last N AgentReflection rows (agent memory / lessons learned)."""
    reflections = (
        db.query(AgentReflection)
        .order_by(AgentReflection.created_at.desc())
        .limit(limit)
        .all()
    )
    result = []
    for r in reflections:
        try:
            tags = json.loads(r.tags or "{}")
        except Exception:
            tags = {}
        try:
            cycle_ids = json.loads(r.episode_cycle_ids or "[]")
        except Exception:
            cycle_ids = []
        result.append({
            "id": r.id,
            "lesson": r.lesson,
            "tags": tags,
            "episode_cycle_ids": cycle_ids,
            "created_at": r.created_at,
        })
    return result


@router.post('/agent/run-cycle')
def trigger_agent_cycle(db: Session = Depends(get_db)):
    """
    Manually trigger one AgentController cycle for testing/demo.
    Does not bypass next_run gating — for a forced run, temporarily set next_run=null via settings.
    """
    import threading
    def _run():
        _agent_controller.run_cycle()
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return {"status": "cycle triggered", "message": "AgentController.run_cycle() running in background"}


@router.get('/agent/template-analytics')
def get_template_analytics(db: Session = Depends(get_db)):
    """
    Compute per-template performance analytics from existing Email + Meeting data.
    No new tables — derived entirely from outreach history.
    Returns stats used by the Template Analytics dashboard tab.
    """
    from datetime import datetime, timedelta
    from apps.api.modules.crm.models import Email, Meeting, OutreachTemplate, Lead
    from collections import defaultdict

    now = datetime.utcnow()
    cutoff_90d = now - timedelta(days=90)

    # All recent emails with template info
    emails = (
        db.query(Email)
        .filter(Email.sent_at >= cutoff_90d)
        .all()
    )

    # All meetings (to count per template)
    all_meetings = db.query(Meeting).all()
    # Map lead_id -> meeting count
    meetings_by_lead: dict = defaultdict(int)
    for m in all_meetings:
        if m.lead_id:
            meetings_by_lead[m.lead_id] += 1

    # Group email stats by template name
    stats: dict = defaultdict(lambda: {
        "template_id": None,
        "total_sent": 0,
        "total_opened": 0,
        "total_replied": 0,
        "total_meetings": 0,
        "last_used": None,
    })

    for em in emails:
        tname = em.outreach_template_name or "(no template)"
        s = stats[tname]
        s["template_id"] = em.outreach_template_id
        s["total_sent"] += 1
        if em.opened_at:
            s["total_opened"] += 1
        if em.replied_at:
            s["total_replied"] += 1
        if em.lead_id and meetings_by_lead[em.lead_id] > 0:
            s["total_meetings"] += meetings_by_lead[em.lead_id]
            meetings_by_lead[em.lead_id] = 0  # count once per lead across templates
        sent_at = em.sent_at
        if sent_at and (s["last_used"] is None or sent_at > s["last_used"]):
            s["last_used"] = sent_at

    # Also include templates with zero emails (so all show up in the dashboard)
    all_templates = db.query(OutreachTemplate).all()
    for t in all_templates:
        if t.name not in stats:
            stats[t.name] = {
                "template_id": t.id,
                "total_sent": 0,
                "total_opened": 0,
                "total_replied": 0,
                "total_meetings": 0,
                "last_used": None,
            }
        else:
            stats[t.name]["template_id"] = t.id  # ensure id is set

    # Compute rates + AI recommendation label
    result = []
    for tname, s in stats.items():
        sent = s["total_sent"]
        replied = s["total_replied"]
        opened = s["total_opened"]
        meetings = s["total_meetings"]
        reply_rate = round(replied / sent, 4) if sent > 0 else 0.0
        open_rate = round(opened / sent, 4) if sent > 0 else 0.0

        # Simple AI recommendation label based on performance
        if sent == 0:
            recommendation = "Not yet tested"
        elif reply_rate >= 0.20:
            recommendation = "Highly Recommended — High reply rate"
        elif reply_rate >= 0.10:
            recommendation = "Recommended — Good reply rate"
        elif meetings > 0:
            recommendation = "Recommended for Meeting Conversion"
        elif sent >= 10 and reply_rate < 0.05:
            recommendation = "Low performance — Consider revising"
        else:
            recommendation = "Needs more data"

        result.append({
            "template_name": tname,
            "template_id": s["template_id"],
            "total_sent": sent,
            "open_rate": open_rate,
            "reply_rate": reply_rate,
            "total_meetings": meetings,
            "last_used": s["last_used"],
            "ai_recommendation": recommendation,
        })

    # Sort: templates with most emails first
    result.sort(key=lambda x: x["total_sent"], reverse=True)
    return result

