"""
Agent Controller — Goal-Directed Autonomous Agent

Replaces AutoAgentRunner as the background scheduler target.
Runs a full perceive → decide → act → log → reflect loop each scheduled cycle.

Architecture: one controller, many tools.
  - The 7 service modules are treated as tools that the controller calls.
  - No service internals are modified; only public methods are called.
  - AutoAgentRunner and OrchestrationService.run_prospecting_pipeline are preserved
    as manual override paths and are not touched here.

Autonomy dial:
  - Safe actions (rescan_signals, re_enrich_lead): always execute autonomously.
  - Risky actions (revise_template, book_meeting, send_email): write a
    pending_approval AgentDecision instead of executing, unless the flag is True.
  - A human calls POST /orchestration/agent/decisions/{id}/approve to execute.
"""

import json
import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from apps.api.db.database import SessionLocal
from apps.api.core.ai_provider import AIProvider
from apps.api.modules.crm.models import AgentSettings, Lead, Contact, Company, Email, Meeting
from apps.api.modules.prospecting.models import ProspectingJob
from apps.api.modules.orchestration.agent_models import AgentGoal, AgentDecision, AgentReflection
from apps.api.modules.knowledge.models import KnowledgeBase

logger = logging.getLogger(__name__)


# ─── Tool descriptions fed to the LLM decision prompt ─────────────────────────
TOOL_MENU = """
Available tools (return a JSON list of ToolCall objects):

tool: discover_more_leads
  purpose: Run a new prospecting search job to add fresh leads to the top of funnel.
  use_when: Goal is NOT on track AND funnel pipeline is empty (ready_for_outreach=0, leads_raw_new<5, leads_need_enrichment=0) AND no jobs running.
  params: {}

tool: re_enrich_lead
  purpose: Run a second enrichment pass for a contact with missing email or title.
  use_when: funnel.leads_need_enrichment > 0
  params: {"contact_id": <int>}

tool: scan_signals_for_lead
  purpose: Run full signal detection + lead scoring for a specific lead that is enriched but not yet scored/scanned.
  use_when: funnel.leads_need_signal_scan > 0
  params: {"lead_id": <int>}

tool: rescan_signals
  purpose: Re-scan ALL leads in new/scored status for refreshed buying signals.
  use_when: A bulk refresh is needed, e.g. signals are stale across many leads.
  params: {}

tool: send_initial_outreach
  purpose: Generate and send initial outreach emails to qualified, ready leads.
  use_when: funnel.leads_ready_for_outreach > 0
  params: {"lead_ids": [<int>, ...]}   # pass up to max_outreach_per_cycle lead IDs

tool: send_followup
  purpose: Generate follow-up emails for leads that have gone quiet (contacted but no reply).
  use_when: funnel.leads_stale > 0
  params: {"days_inactive": <int, default 3>}

tool: book_meeting
  purpose: Attempt to schedule a meeting with a lead that has already replied positively.
  use_when: funnel.leads_replied_no_meeting > 0 AND goal=meetings_booked
  params: {"lead_id": <int>}

tool: revise_template
  purpose: Switch to a fixed template OR provide a stylistic hint to improve AI-generated emails.
  use_when: outreach.underperforming_variant is not null
  params: {"template_id": <int or null>, "revision_hint": <str or null>}

tool: do_nothing_this_cycle
  purpose: Take no action this cycle. Log reasoning.
  use_when: Goal IS on track OR all queues are empty.
  params: {}

Return JSON format:
{
  "tool_calls": [
    {"action": "<tool_name>", "params": {<params>}, "reasoning": "<why you chose this>"},
    ...
  ]
}
You may return multiple tool calls if the situation warrants it. Prefer fewer, more targeted actions.
"""

# ─── Template selector prompt (used when outreach_strategy == "ai_select") ─────
TEMPLATE_SELECT_SYSTEM = """You are the outreach template selector for SETV, an autonomous B2B healthcare sales agent.
Your job is to choose the single best outreach template for the next email batch based on:
  1. The agent's current goal
  2. Historical template performance (reply rate, meetings generated)
  3. Past lessons from agent memory

Goal-to-template guidance:
  - replies_received   → prefer "Cold Outreach" or "Product Introduction"
  - meetings_booked    → prefer "Meeting Request" or "Demo Invitation"
  - leads_qualified    → prefer "Cold Outreach" or "Product Introduction"
  - leads_persisted    → prefer "Cold Outreach"
  - (follow-up needed) → prefer "Follow-up"

Return a JSON object:
{
  "template_id": <int or null>,
  "template_name": "<name>",
  "reasoning": "<1-2 sentence explanation citing performance data or past lessons>",
  "confidence": <float 0.0–1.0>
}
If no template data exists, reason from goal alone and set confidence to 0.5."""

DECISION_SYSTEM = """You are the AgentController for SETV, an autonomous healthcare B2B sales agent.
Your job is to decide which action(s) to take this cycle based on the goal, current funnel state, and past lessons.
You must return a valid JSON object with a \"tool_calls\" array as specified.
Be concise in your reasoning (1-2 sentences per action). Do NOT invent data not present in the state snapshot.

Lead Lifecycle: NEW → ENRICHED → SCORED/SIGNALS → QUALIFIED (score≥70) → CONTACTED → REPLIED → MEETING
You must clear pipeline gates in order before sending outreach. A lead needs a verified email AND a score before it can be emailed."""

REFLECTION_SYSTEM = """You are the learning module for the SETV AgentController.
Based on the decisions taken this cycle and their outcomes, write a short distilled lesson (1-2 sentences).
Be concrete about what happened: which outreach template was used (if any), what the outcome was, and what should be done differently next time.
If a template was used, name it explicitly in the lesson (e.g. "Cold Outreach template", "Meeting Request template").
Return a JSON object:
{
  "lesson": "<1-2 sentence lesson>",
  "tags": {"template_name": <str or null>, "template_hash": <str or null>, "provider": <str or null>, "segment": <str or null>, "lead_id": <int or null>}
}
Only include tag keys that are directly relevant to the lesson. Leave irrelevant keys as null."""


def _save_error_state(db, job_id, interval_minutes: int, error_msg: str, logs: list):
    """
    Module-level helper: safely persists error state to the DB
    using whatever session is passed in. Called when any cycle phase fails.
    """
    try:
        from apps.api.modules.orchestration.agent_models import AgentSettings
        from apps.api.modules.prospecting.models import ProspectingJob
        settings = db.query(AgentSettings).first()
        if settings:
            settings.current_status = "Error"
            settings.current_stage = None
            settings.next_run = datetime.now(timezone.utc) + timedelta(minutes=(interval_minutes or 5))
        if job_id:
            job = db.query(ProspectingJob).filter(ProspectingJob.id == job_id).first()
            if job:
                job.status = "Error"
                job.error_message = error_msg
                job.completed_at = datetime.now(timezone.utc)
                job.execution_logs = json.dumps(logs)
        db.commit()
    except Exception as e:
        logger.error("[AgentController] _save_error_state failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass


class AgentController:
    """
    Goal-directed agent controller.
    Replaces AutoAgentRunner as the scheduler target.
    """

    def __init__(self):
        # Import services lazily inside methods to avoid circular imports at startup.
        pass

    # ─── Public entry point ────────────────────────────────────────────────────

    def run_cycle(self):
        """
        Main entry point called by the APScheduler every minute.

        Uses THREE short-lived DB sessions to prevent TCP connection aborts:
          Session 1 → Perceive (load state, mark Running, then close DB)
          Session 2 → Act + Log decisions (open fresh DB after AI decides)
          Session 3 → Reflect + Finalize (open fresh DB after AI reflects)

        This ensures no DB connection is held open during slow LLM inference,
        which prevents: psycopg2.OperationalError / SSL SYSCALL connection abort.
        """
        db = None
        cycle_id = str(uuid.uuid4())
        job_id = None
        interval_minutes = 5  # safe default
        logs = []

        def log_step(msg: str):
            logger.info(f"[AgentController] {msg}")
            logs.append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")

        # ── SESSION 1: Gate-check, Perceive, then CLOSE the DB ───────────────
        db = SessionLocal()
        try:
            settings = db.query(AgentSettings).first()
            if not settings:
                settings = AgentSettings()
                db.add(settings)
                db.commit()

            if not settings.enabled:
                return

            now = datetime.now(timezone.utc)
            interval_minutes = settings.interval_minutes  # snapshot before closing

            if settings.next_run:
                next_run = settings.next_run if settings.next_run.tzinfo else settings.next_run.replace(tzinfo=timezone.utc)
                if next_run > now:
                    return

            if settings.current_status == "Running":
                logger.info("[AgentController] Already running, skipping this poll.")
                return

            # Create job log row
            job = ProspectingJob(status="Agent Cycle", started_at=now)
            db.add(job)
            db.commit()
            db.refresh(job)
            job_id = job.id

            # Mark agent as Running
            settings.current_status = "Running"
            settings.current_stage = "Perceiving"
            settings.last_run = now
            db.commit()

            log_step(f"Starting Cycle {cycle_id[:8]}...")

            # Perceive — all DB reads happen here
            goal = self._get_or_create_goal(db)
            state = self.perceive(db, goal)
            log_step(f"Perceived State: {state.get('stale_leads', {}).get('count', 0)} stale leads, {state.get('pipeline', {}).get('running_jobs', 0)} running jobs.")

            # Snapshot plain-Python values so we can use them after DB closes
            goal_id = goal.id
            goal_snapshot = {
                "id": goal.id,
                "target_metric": goal.target_metric,
                "target_value": goal.target_value,
                "outreach_strategy": getattr(goal, 'outreach_strategy', 'fixed'),
                "reflect_every_n_cycles": goal.reflect_every_n_cycles,
                "cycles_since_last_reflection": goal.cycles_since_last_reflection,
                "auto_rescan_signals": goal.auto_rescan_signals,
                "auto_re_enrich_lead": goal.auto_re_enrich_lead,
                "auto_revise_template": goal.auto_revise_template,
                "auto_book_meeting": goal.auto_book_meeting,
                "min_sample_for_revision": goal.min_sample_for_revision,
                "reply_rate_floor": getattr(goal, 'reply_rate_floor', 0.05),
                "active_revision_json": goal.active_revision_json,
            }
            relevant_reflections = self._get_relevant_reflections(db, state)

            # ✅ CLOSE DB before slow AI calls — releases TCP connection
            db.commit()
            db.close()
            db = None

        except Exception as exc:
            logger.error("[AgentController] Perceive error in cycle %s: %s", cycle_id, exc, exc_info=True)
            log_step(f"ERROR during Perceive: {exc}")
            if db:
                db.rollback()
                db.close()
                db = None
            db_err = SessionLocal()
            try:
                _save_error_state(db_err, job_id, interval_minutes, str(exc), logs)
            finally:
                db_err.close()
            return

        # ── DECIDE (AI call — no DB connection held) ─────────────────────────
        try:
            log_step("Deciding next actions...")
            tool_calls = self.decide(state, goal_snapshot, relevant_reflections)
            decided_actions = [tc.get("action") for tc in tool_calls]
            log_step(f"Decided: {decided_actions}")
        except Exception as exc:
            logger.error("[AgentController] Decide error in cycle %s: %s", cycle_id, exc, exc_info=True)
            log_step(f"ERROR during Decide: {exc}")
            db_err = SessionLocal()
            try:
                _save_error_state(db_err, job_id, interval_minutes, str(exc), logs)
            finally:
                db_err.close()
            return

        # ── SESSION 2: Act + Log decisions (fresh DB after AI finished) ───────
        db2 = SessionLocal()
        try:
            goal2 = db2.query(AgentGoal).filter(AgentGoal.id == goal_id).first()
            settings2 = db2.query(AgentSettings).first()
            settings2.current_stage = "Acting"
            db2.commit()

            outcomes = self.act(db2, tool_calls, goal2, settings2, cycle_id, state)

            for tc, outcome in zip(tool_calls, outcomes):
                self.log_decision(
                    db=db2,
                    cycle_id=cycle_id,
                    goal=goal2,
                    state=state,
                    action=tc["action"],
                    params=tc.get("params", {}),
                    reasoning=tc.get("reasoning", ""),
                    status=outcome.get("status", "executed"),
                    outcome=outcome,
                )

            # ── Reflect ───────────────────────────────────────────────────────
            goal.cycles_since_last_reflection += 1
            db.commit()

            if goal.cycles_since_last_reflection >= goal.reflect_every_n_cycles:
                settings.current_stage = "Reflecting"
                db.commit()
                self.reflect(db, cycle_id, tool_calls, outcomes)
                goal.cycles_since_last_reflection = 0
                db.commit()

            # ── Finalize ──────────────────────────────────────────────────────
            settings.current_status = "Idle"
            settings.current_stage = None
            settings.next_run = datetime.now(timezone.utc) + timedelta(minutes=settings.interval_minutes)
            
            job.status = "Completed"
            job.completed_at = datetime.now(timezone.utc)
            
            db.commit()
            log_step(f"Cycle {cycle_id[:8]} complete.")

        except Exception as exc:
            db.rollback()
            logger.error("[AgentController] Cycle %s error: %s", cycle_id, exc, exc_info=True)
            if 'log_step' in locals():
                log_step(f"ERROR: {exc}")
            
            # Re-fetch settings/job in a fresh transaction to ensure we can save the error state
            try:
                if settings:
                    fresh_settings = db.query(AgentSettings).first()
                    if fresh_settings:
                        fresh_settings.current_status = "Error"
                        fresh_settings.current_stage = None
                        fresh_settings.next_run = datetime.now(timezone.utc) + timedelta(minutes=settings.interval_minutes)
                if 'job' in locals() and job and job.id:
                    fresh_job = db.query(ProspectingJob).filter(ProspectingJob.id == job.id).first()
                    if fresh_job:
                        fresh_job.status = "Error"
                        fresh_job.error_message = str(exc)
                        fresh_job.completed_at = datetime.now(timezone.utc)
                        if 'logs' in locals():
                            fresh_job.execution_logs = json.dumps(logs)
                db.commit()
            except Exception as nested_exc:
                logger.error("[AgentController] Failed to save error state: %s", nested_exc)
        finally:
            if 'job' in locals() and job and hasattr(job, 'status') and job.status != "Error":
                # Only update logs here if we didn't already hit the exception block
                job.execution_logs = json.dumps(logs)
                db.commit()
            db.close()

    # ─── perceive ─────────────────────────────────────────────────────────────

    def perceive(self, db: Session, goal: AgentGoal) -> dict:
        """
        Query actual state from the CRM/DB.
        Returns a rich funnel census that is fed to decide() and stored in AgentDecision.
        Each section of the state snapshot maps to a stage in the lead lifecycle.
        """
        now = datetime.now(timezone.utc)

        # ── 1. Goal period boundaries ──────────────────────────────────────────
        if goal.period == "daily":
            period_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            days_since_monday = now.weekday()
            period_start = (now - timedelta(days=days_since_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )

        goal_progress = self._measure_goal_progress(db, goal.target_metric, period_start)

        # ── 2. Funnel census (each stage gate) ────────────────────────────────
        # Gate 1: Enrichment — leads with contacts missing verified email or title
        all_leads = db.query(Lead).filter(Lead.status.in_(["new", "scored"])).all()
        lead_ids_need_enrichment = []
        contact_ids_need_enrichment = []
        lead_ids_need_signal_scan = []
        leads_raw_new = 0

        for lead in all_leads:
            if lead.status == "new":
                leads_raw_new += 1
            if lead.contact_id:
                from apps.api.modules.crm.models import Contact
                contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
                if contact:
                    needs_enrich = (
                        not contact.email
                        or contact.email == "unknown@example.com"
                        or "@no-email-provided" in contact.email
                        or not contact.title
                    )
                    if needs_enrich:
                        lead_ids_need_enrichment.append(lead.id)
                        contact_ids_need_enrichment.append(lead.contact_id)
                    else:
                        # Has email + title — does it have a fresh signal scan?
                        from apps.api.modules.signals.repository import SignalsRepository
                        repo = SignalsRepository()
                        if not repo.has_recent_scan(db, lead.id, hours=24):
                            lead_ids_need_signal_scan.append(lead.id)

        # Gate 3: Qualified leads ready to contact (have score, fresh signals, email)
        QUALIFICATION_THRESHOLD = 40  # same as config
        qualified_ready = db.query(Lead).filter(
            Lead.status == "scored",
            Lead.lead_score >= QUALIFICATION_THRESHOLD,
        ).all()
        # Filter to only those not in the needs-enrich bucket
        enrich_set = set(contact_ids_need_enrichment)
        leads_ready_ids = []
        for l in qualified_ready:
            if l.contact_id not in enrich_set:
                leads_ready_ids.append(l.id)

        # Gate 4: Stale (contacted > 3 days, no reply)
        stale_cutoff = now - timedelta(days=3)
        stale_leads = db.query(Lead).filter(
            Lead.status == "contacted",
            Lead.last_activity_at < stale_cutoff,
        ).limit(20).all()

        # Gate 5: Replied, no meeting yet
        replied_no_meeting = db.query(Lead).filter(
            Lead.status == "replied",
        ).all()
        replied_no_meeting_ids = []
        for l in replied_no_meeting:
            has_meeting = db.query(Meeting).filter(Meeting.lead_id == l.id).first()
            if not has_meeting:
                replied_no_meeting_ids.append(l.id)

        # ── 3. Outreach stats ─────────────────────────────────────────────────
        cutoff_30d = now - timedelta(days=30)
        recent_emails = (
            db.query(Email)
            .filter(Email.sent_at >= cutoff_30d)
            .order_by(Email.sent_at.desc())
            .limit(60)
            .all()
        )
        total_sent = len(recent_emails)
        total_replied = sum(1 for e in recent_emails if e.replied_at is not None)
        overall_reply_rate = (total_replied / total_sent) if total_sent > 0 else 0.0

        from collections import defaultdict
        variant_stats: dict[str, dict] = defaultdict(lambda: {"sends": 0, "replies": 0})
        for em in recent_emails:
            if em.outreach_template_id:
                key = f"template_{em.outreach_template_id}"
            else:
                key = (em.subject or "")[:40].strip() if em.subject else "no_subject"
            variant_stats[key]["sends"] += 1
            if em.replied_at:
                variant_stats[key]["replies"] += 1

        underperforming_variant = None
        for key, stats in variant_stats.items():
            sends = stats["sends"]
            replies = stats["replies"]
            rate = (replies / sends) if sends > 0 else 0.0
            stats["reply_rate"] = round(rate, 4)
            if sends >= goal.min_sample_for_revision and rate < goal.reply_rate_floor:
                if underperforming_variant is None or rate < underperforming_variant["reply_rate"]:
                    underperforming_variant = {"subject_snippet": key, "sends": sends, "replies": replies, "reply_rate": rate}

        # ── 4. Pipeline load ──────────────────────────────────────────────────
        running_jobs = db.query(ProspectingJob).filter(
            ProspectingJob.status == "Running",
            ProspectingJob.started_at >= now - timedelta(hours=2)
        ).count()

        # ── 5. Provider health ────────────────────────────────────────────────
        recent_decisions = (
            db.query(AgentDecision)
            .filter(AgentDecision.created_at >= now - timedelta(hours=2))
            .order_by(AgentDecision.created_at.desc())
            .limit(20)
            .all()
        )
        provider_health: dict[str, str] = {}
        for dec in recent_decisions:
            if dec.outcome:
                try:
                    out = json.loads(dec.outcome)
                    provider = out.get("provider")
                    outcome = out.get("outcome")
                    if provider and outcome in ("provider_error", "rate_limited"):
                        provider_health[provider] = outcome
                except Exception:
                    pass

        # ── 6. Available Templates + Performance Stats ────────────────────────
        from apps.api.modules.crm.models import OutreachTemplate
        available_templates = db.query(OutreachTemplate).all()
        outreach_templates_state = [
            {"id": t.id, "name": t.name, "is_default": t.is_default, "category": getattr(t, 'category', None)}
            for t in available_templates
        ]

        # Compute per-template performance from raw Email history (no new tables)
        template_stats: dict = {}
        for em in recent_emails:
            tname = em.outreach_template_name or "(no template)"
            if tname not in template_stats:
                template_stats[tname] = {"sent": 0, "replied": 0, "template_id": em.outreach_template_id}
            template_stats[tname]["sent"] += 1
            if em.replied_at:
                template_stats[tname]["replied"] += 1
        for k, v in template_stats.items():
            s = v["sent"]
            v["reply_rate"] = round(v["replied"] / s, 4) if s > 0 else 0.0

        # ── 7. SETV Knowledge Base ────────────────────────────────────────────
        kb_record = db.query(KnowledgeBase).order_by(KnowledgeBase.version.desc()).first()
        setv_knowledge = kb_record.data if kb_record else {}

        return {
            "timestamp": now.isoformat(),
            "goal": {
                "target_metric": goal.target_metric,
                "target_value": goal.target_value,
                "period": goal.period,
                "period_start": period_start.isoformat(),
            },
            "goal_progress": {
                "current": goal_progress,
                "target": goal.target_value,
                "pct": round((goal_progress / goal.target_value) * 100, 1) if goal.target_value > 0 else 0,
                "on_track": goal_progress >= goal.target_value,
            },
            # Full funnel census
            "funnel": {
                "leads_raw_new": leads_raw_new,
                "leads_need_enrichment": len(lead_ids_need_enrichment),
                "contact_ids_need_enrichment": contact_ids_need_enrichment[:5],
                "leads_need_signal_scan": len(lead_ids_need_signal_scan),
                "lead_ids_need_signal_scan": lead_ids_need_signal_scan[:5],
                "leads_ready_for_outreach": len(leads_ready_ids),
                "lead_ids_ready": leads_ready_ids[:10],
                "leads_stale": len(stale_leads),
                "lead_ids_stale": [l.id for l in stale_leads[:5]],
                "leads_in_outreach": db.query(Lead).filter(Lead.status == "contacted").count(),
                "leads_replied_no_meeting": len(replied_no_meeting_ids),
                "lead_ids_replied_no_meeting": replied_no_meeting_ids[:5],
            },
            "outreach": {
                "total_sent_period": total_sent,
                "total_replied_period": total_replied,
                "overall_reply_rate": round(overall_reply_rate, 4),
                "underperforming_variant": underperforming_variant,
                "available_templates": outreach_templates_state,
                "template_stats": template_stats,
                "outreach_strategy": getattr(goal, 'outreach_strategy', 'fixed'),
            },
            "pipeline": {
                "running_jobs": running_jobs,
            },
            "provider_health": provider_health,
            "setv_knowledge": setv_knowledge,
        }

    # ─── decide ───────────────────────────────────────────────────────────────

    def decide(self, state: dict, goal: AgentGoal, reflections: list[str]) -> list[dict]:
        """
        LLM-driven action selector.
        Returns a list of ToolCall dicts: [{"action": str, "params": dict, "reasoning": str}]
        Falls back to a rule-based default if the LLM call fails.
        """

        reflection_block = ""
        if reflections:
            reflection_block = "\n\n--- PAST LESSONS (use these to inform your decision) ---\n"
            reflection_block += "\n".join(f"• {r}" for r in reflections)
            reflection_block += "\n---"

        # Build goal-aware strategy block so agent understands the current priority ordering
        metric = goal.target_metric
        if metric in ("leads_persisted", "leads_qualified"):
            strategy_block = """\n--- CURRENT GOAL STRATEGY: DISCOVERY ---
Your goal is top-of-funnel lead acquisition. Priority order:
1. re_enrich_lead → if funnel.leads_need_enrichment > 0 (clear enrichment gate first)
2. scan_signals_for_lead → if funnel.leads_need_signal_scan > 0 (score leads before counting them)
3. discover_more_leads → if NOT on track AND pipeline.running_jobs == 0
4. do_nothing_this_cycle → if on track"""
        else:
            strategy_block = """\n--- CURRENT GOAL STRATEGY: CONVERSION ---
Your goal is to convert existing leads. Work closest-to-goal first:
1. book_meeting → if funnel.leads_replied_no_meeting > 0 AND goal=meetings_booked
2. send_followup → if funnel.leads_stale > 0
3. send_initial_outreach → if funnel.leads_ready_for_outreach > 0 (PREFERRED over discovering new leads)
4. scan_signals_for_lead → if funnel.leads_need_signal_scan > 0 (prepare next outreach batch)
5. re_enrich_lead → if funnel.leads_need_enrichment > 0 (prepare next outreach batch)
6. discover_more_leads → ONLY if funnel.leads_ready_for_outreach==0 AND funnel.leads_raw_new<5 AND funnel.leads_need_enrichment==0 AND NOT on track
7. do_nothing_this_cycle → if on track
NEVER choose discover_more_leads if you have leads ready to contact."""

        prompt = f"""Current goal:
{json.dumps(state['goal'], indent=2)}

Goal progress this period:
{json.dumps(state['goal_progress'], indent=2)}

Funnel census (lead counts at each pipeline stage):
{json.dumps(state['funnel'], indent=2)}

Outreach performance:
{json.dumps(state['outreach'], indent=2)}

Pipeline load:
{json.dumps(state['pipeline'], indent=2)}

Provider health (unhealthy providers listed with error type):
{json.dumps(state['provider_health'], indent=2)}

SETV Knowledge Base (latest products/services to frame context):
{json.dumps(state.get('setv_knowledge', {}), indent=2)}
{reflection_block}
{strategy_block}

{TOOL_MENU}
"""
        try:
            result = AIProvider().generate_content(
                system_instruction=DECISION_SYSTEM,
                prompt=prompt,
            )
            tool_calls = result.get("tool_calls", [])
            if isinstance(tool_calls, list) and len(tool_calls) > 0:
                valid = []
                for tc in tool_calls:
                    if isinstance(tc, dict) and "action" in tc:
                        tc.setdefault("params", {})
                        tc.setdefault("reasoning", "")
                        valid.append(tc)
                if valid:
                    return valid
        except Exception as exc:
            logger.error("[AgentController.decide] LLM call failed: %s", exc, exc_info=True)

        return self._rule_based_fallback(state, goal)

    def _rule_based_fallback(self, state: dict, goal: AgentGoal) -> list[dict]:
        """Priority-ordered fallback matching the same goal-aware strategy as decide()."""

        metric = goal.target_metric
        funnel = state.get("funnel", {})
        on_track = state["goal_progress"]["on_track"]
        running_jobs = state["pipeline"]["running_jobs"]

        uv = state["outreach"].get("underperforming_variant")

        # For CONVERSION goals (replies, meetings) — prioritize pipeline clearance top-down
        if metric in ("replies_received", "meetings_booked"):
            if metric == "meetings_booked" and funnel.get("leads_replied_no_meeting", 0) > 0:
                lead_id = funnel["lead_ids_replied_no_meeting"][0]
                return [{"action": "book_meeting", "params": {"lead_id": lead_id}, "reasoning": "Replied lead awaiting meeting booking (fallback rule)."}]
            if funnel.get("leads_stale", 0) > 0:
                return [{"action": "send_followup", "params": {"days_inactive": 3}, "reasoning": "Stale leads need follow-up (fallback rule)."}]
            if funnel.get("leads_ready_for_outreach", 0) > 0:
                ids = funnel.get("lead_ids_ready", [])[:3]
                return [{"action": "send_initial_outreach", "params": {"lead_ids": ids}, "reasoning": f"{len(ids)} qualified leads ready for outreach (fallback rule)."}]
            if uv:
                return [{"action": "revise_template", "params": uv, "reasoning": f"Reply rate {uv['reply_rate']:.1%} below floor (fallback rule)."}]

        # For DISCOVERY goals — top-down enrichment then discover
        if metric in ("leads_persisted", "leads_qualified"):
            if funnel.get("leads_need_enrichment", 0) > 0:
                cid = funnel["contact_ids_need_enrichment"][0]
                return [{"action": "re_enrich_lead", "params": {"contact_id": cid}, "reasoning": "Contact missing email (fallback rule)."}]
            if funnel.get("leads_need_signal_scan", 0) > 0:
                lid = funnel["lead_ids_need_signal_scan"][0]
                return [{"action": "scan_signals_for_lead", "params": {"lead_id": lid}, "reasoning": "Lead needs signal scan + scoring (fallback rule)."}]

        # Universal: clear enrichment/scoring gates before discovering more
        if funnel.get("leads_need_enrichment", 0) > 0:
            cid = funnel["contact_ids_need_enrichment"][0]
            return [{"action": "re_enrich_lead", "params": {"contact_id": cid}, "reasoning": "Contact missing email (fallback rule)."}]
        if funnel.get("leads_need_signal_scan", 0) > 0:
            lid = funnel["lead_ids_need_signal_scan"][0]
            return [{"action": "scan_signals_for_lead", "params": {"lead_id": lid}, "reasoning": "Lead needs signal scan + scoring (fallback rule)."}]

        # Only discover if pipeline is truly empty and not on track
        if not on_track and running_jobs == 0:
            pipeline_empty = (
                funnel.get("leads_ready_for_outreach", 0) == 0
                and funnel.get("leads_raw_new", 0) < 5
                and funnel.get("leads_need_enrichment", 0) == 0
            )
            if pipeline_empty:
                return [{"action": "discover_more_leads", "params": {}, "reasoning": "Pipeline truly empty, behind target (fallback rule)."}]

        return [{"action": "do_nothing_this_cycle", "params": {}, "reasoning": "No urgent action needed (fallback rule)."}]

    # ─── act ──────────────────────────────────────────────────────────────────

    def act(
        self,
        db: Session,
        tool_calls: list[dict],
        goal: AgentGoal,
        settings: AgentSettings,
        cycle_id: str,
        state: dict,
        force: bool = False,
    ) -> list[dict]:
        """
        Execute each tool call.
        If the autonomy flag for an action is False, write a pending_approval
        AgentDecision instead of executing — UNLESS force=True (approval path).
        force=True is only set by execute_pending_decision(); normal run_cycle() always uses force=False.
        """
        from apps.api.modules.prospecting.service import ProspectingService
        from apps.api.modules.signals.service import SignalsService
        from apps.api.modules.outreach.service import OutreachService

        prospecting_svc = ProspectingService()
        signals_svc = SignalsService()
        outreach_svc = OutreachService()

        outcomes = []
        for tc in tool_calls:
            action = tc.get("action", "do_nothing_this_cycle")
            params = tc.get("params", {})
            outcome: dict = {}

            try:
                # ── do_nothing_this_cycle ─────────────────────────────────────
                if action == "do_nothing_this_cycle":
                    outcome = {"status": "skipped", "reason": tc.get("reasoning", "")}

                # ── discover_more_leads ───────────────────────────────────────
                elif action == "discover_more_leads":
                    # Always autonomous — discovering leads is safe / reversible.
                    # Bug 6: cleanup any stale "Running" jobs before spawning a new one
                    from apps.api.modules.crm.models import JobTemplate
                    from sqlalchemy.sql.expression import func as sqlfunc
                    stale_cutoff = datetime.now(timezone.utc) - timedelta(hours=2)
                    stale_running = db.query(ProspectingJob).filter(
                        ProspectingJob.status == "Running",
                        ProspectingJob.started_at < stale_cutoff,
                    ).all()
                    for stale_job in stale_running:
                        stale_job.status = "Error"
                        stale_job.error_message = "Timed out — marked by AgentController before new job"
                        stale_job.completed_at = datetime.now(timezone.utc)
                    if stale_running:
                        db.flush()
                        logger.warning("[AgentController] Cleaned up %d stale Running jobs", len(stale_running))

                    template = None
                    if settings.default_template_id:
                        template = db.query(JobTemplate).filter(
                            JobTemplate.id == settings.default_template_id
                        ).first()
                    if not template:
                        template = db.query(JobTemplate).order_by(sqlfunc.random()).first()

                    if template:
                        from apps.api.modules.prospecting.engine.schemas.internal import ICPFilter
                        import threading
                        import asyncio

                        icp = ICPFilter(
                            regions=[template.regions] if template.regions else ["US"],
                            industries=[template.industries] if template.industries else ["Healthcare"],
                            keywords=[k.strip() for k in (template.keywords or "").split(",") if k.strip()],
                        )
                        job = prospecting_svc.create_search_job(db, icp.model_dump())

                        def _run_async(job_id, icp_filter):
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            try:
                                loop.run_until_complete(
                                    prospecting_svc.run_job_async_wrapper(job_id, icp_filter)
                                )
                            finally:
                                loop.close()

                        t = threading.Thread(target=_run_async, args=(job.id, icp), daemon=True)
                        t.start()
                        outcome = {"status": "executed", "job_id": job.id, "template": template.name}
                    else:
                        outcome = {"status": "skipped", "reason": "No job template found"}

                # ── scan_signals_for_lead ────────────────────────────────────────────
                elif action == "scan_signals_for_lead":
                    lead_id = params.get("lead_id")
                    if not lead_id:
                        scan_ids = state.get("funnel", {}).get("lead_ids_need_signal_scan", [])
                        lead_id = scan_ids[0] if scan_ids else None
                    if lead_id:
                        result = signals_svc.scan_lead_signals(db, lead_id)
                        db.flush()
                        outcome = {"status": "executed", **result}
                    else:
                        outcome = {"status": "skipped", "reason": "No lead to scan"}

                # ── send_initial_outreach (batch) ────────────────────────────────────
                elif action == "send_initial_outreach":
                    # Support both single lead_id (legacy) and lead_ids list (new batch mode)
                    lead_ids = params.get("lead_ids") or []
                    if not lead_ids and params.get("lead_id"):
                        lead_ids = [params["lead_id"]]
                    if not lead_ids:
                        # Pull from funnel state, capped by max_outreach_per_cycle setting
                        max_batch = getattr(settings, "max_outreach_per_cycle", 3) or 3
                        lead_ids = state.get("funnel", {}).get("lead_ids_ready", [])[:max_batch]
                        if not lead_ids:
                            # Fallback: any scored lead above threshold not yet contacted
                            ql = db.query(Lead).filter(
                                Lead.status == "scored",
                                Lead.lead_score >= 40,
                            ).limit(3).all()
                            lead_ids = [l.id for l in ql]

                    # Apply daily limit check for initial outreach
                    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    sent_today = db.query(Email).filter(Email.sent_at >= today_start).count()
                    if sent_today >= settings.daily_email_limit:
                        outcome = {"status": "skipped", "reason": "daily_email_limit_reached"}
                        outcomes.append(outcome)
                        continue

                    # ── AGENT CONTROLLER: Template Selection ─────────────────────────
                    # The controller selects the template according to the outreach strategy.
                    # This is where the agent's goal, memory, and performance data converge.
                    selected_template = None
                    template_selection_reasoning = ""
                    template_confidence = None
                    relevant_reflections_for_template = self._get_relevant_reflections(db, state)

                    sel = self._select_outreach_template(
                        db=db,
                        goal=goal,
                        settings=settings,
                        state=state,
                        reflections=relevant_reflections_for_template,
                    )
                    if sel.get("template_id"):
                        from apps.api.modules.crm.models import OutreachTemplate
                        selected_template = db.query(OutreachTemplate).filter(
                            OutreachTemplate.id == sel["template_id"]
                        ).first()
                    template_selection_reasoning = sel.get("reasoning", "")
                    template_confidence = sel.get("confidence")

                    # Store selection context in tc so log_decision can capture it
                    tc["_template_name"] = sel.get("template_name", "AI Generated")
                    tc["_template_confidence"] = template_confidence
                    tc["_template_reasoning"] = template_selection_reasoning

                    drafted_count = 0
                    sent_count = 0
                    skipped_count = 0
                    for lead_id in lead_ids:
                        try:
                            with db.begin_nested():
                                lead = db.query(Lead).filter(Lead.id == lead_id).first()
                                if not lead:
                                    skipped_count += 1
                                    continue
                                # Pull fresh signal context from DB
                                from apps.api.modules.crm.models import Signal
                                signals = db.query(Signal).filter(Signal.lead_id == lead_id)\
                                    .order_by(Signal.score_contribution.desc()).limit(3).all()
                                sig_summary = "; ".join([s.headline for s in signals if s.headline])
                                if not sig_summary:
                                    sig_summary = f"Lead score: {lead.lead_score}, Priority: {lead.priority}"

                                # Use agent-selected template; fall back to revision hint if none
                                revision_hint = ""
                                if not selected_template:
                                    revision_hint = self._get_active_revision_hint(goal)

                                res = outreach_svc.generate_initial_outreach(
                                    db, lead_id,
                                    signal_summary=sig_summary,
                                    template=selected_template,
                                    revision_hint=revision_hint,
                                )
                                
                                if res.get("skipped"):
                                    skipped_count += 1
                                else:
                                    if not res.get("was_draft"):
                                        drafted_count += 1
                                    if settings.auto_send_emails or force:
                                        if sent_today + sent_count >= settings.daily_email_limit:
                                            logger.info("[AgentController] Daily limit reached during initial outreach.")
                                            continue
                                            
                                        from apps.api.modules.email.service import EmailService
                                        try:
                                            email_svc = EmailService(db)
                                            email_id = res.get("email_id")
                                            if email_id:
                                                email_svc.send_email_by_id(email_id)
                                                sent_count += 1
                                        except Exception as send_exc:
                                            logger.warning("Auto-send failed for lead %s: %s", lead_id, send_exc)

                        except Exception as lead_exc:
                            logger.warning("Outreach failed for lead %s: %s", lead_id, lead_exc)
                            skipped_count += 1

                    if drafted_count > 0 or sent_count > 0 or skipped_count > 0:
                        outcome = {
                            "status": "executed",
                            "outreach_drafted": drafted_count,
                            "outreach_sent": sent_count,
                            "skipped": skipped_count,
                            "selected_template": tc.get("_template_name"),
                            "template_confidence": template_confidence,
                            "template_reasoning": template_selection_reasoning,
                        }
                    elif lead_ids:
                        outcome = {"status": "pending_approval", "action": action, "params": {"lead_ids": lead_ids}}
                    else:
                        outcome = {"status": "skipped", "reason": "No qualified lead to contact"}

                # ── send_followup ─────────────────────────────────────────────
                elif action == "send_followup":
                    days_inactive = params.get("days_inactive", 3)
                    from apps.api.modules.outreach.service import OutreachService
                    outreach_svc = OutreachService()
                    # Apply daily limit check for follow-ups too
                    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
                    sent_today = db.query(Email).filter(Email.sent_at >= today_start).count()
                    if sent_today >= settings.daily_email_limit:
                        outcome = {"status": "skipped", "reason": "daily_email_limit_reached"}
                        outcomes.append(outcome)
                        continue

                    results = outreach_svc.process_all_followups(db, days_inactive=days_inactive)
                    
                    drafted = 0
                    sent = 0
                    from apps.api.modules.email.service import EmailService
                    email_svc = EmailService(db)
                    
                    for r in results:
                        if not r.get("skipped"):
                            if not r.get("was_draft"):
                                drafted += 1
                            if settings.auto_send_emails:
                                if sent_today + sent >= settings.daily_email_limit:
                                    logger.info("[AgentController] Reached daily limit during follow-up batch.")
                                    # We don't break the drafting loop natively if they're already drafted, 
                                    # but we stop sending them. Wait, `results` already has them drafted.
                                    # So we just skip sending.
                                    continue
                                
                                email_id = r.get("email_id")
                                if email_id:
                                    try:
                                        email_svc.send_email_by_id(email_id)
                                        sent += 1
                                    except Exception as e:
                                        logger.error("[AgentController] Failed to auto-send followup %s: %s", email_id, e)
                    
                    outcome = {"status": "executed", "followups_drafted": drafted, "followups_sent": sent}

                # ── rescan_signals (bulk) ────────────────────────────────────────────
                elif action == "rescan_signals":
                    if goal.auto_rescan_signals or force:
                        results = signals_svc.scan_all_eligible_leads(db)
                        db.flush()
                        scanned = sum(1 for r in results if not r.get("skipped"))
                        outcome = {"status": "executed", "leads_scanned": scanned}
                    else:
                        outcome = {"status": "pending_approval", "action": action, "params": params}

                # ── re_enrich_lead ────────────────────────────────────────────
                elif action == "re_enrich_lead":
                    contact_id = params.get("contact_id")
                    if not contact_id:
                        # Pull from new funnel state first, then legacy enrichment key
                        enrich_ids = state.get("funnel", {}).get("contact_ids_need_enrichment", [])
                        if not enrich_ids:
                            enrich_ids = state.get("enrichment", {}).get("thin_contact_ids", [])
                        contact_id = enrich_ids[0] if enrich_ids else None

                    if contact_id and (goal.auto_re_enrich_lead or force):
                        result = prospecting_svc.re_enrich_contact(db, contact_id)
                        outcome = {"status": "executed", **result}
                        if result.get("outcome") in ("provider_error", "rate_limited"):
                            outcome["provider_health_signal"] = result["outcome"]
                    elif contact_id:
                        outcome = {"status": "pending_approval", "action": action, "params": {"contact_id": contact_id}}
                    else:
                        outcome = {"status": "skipped", "reason": "No thin contact to enrich"}



                # ── book_meeting ──────────────────────────────────────────────
                elif action == "book_meeting":
                    if goal.auto_book_meeting or force:
                        lead_id = params.get("lead_id")
                        if lead_id:
                            from apps.api.modules.meetings.service import MeetingsService
                            from datetime import timedelta
                            lead = db.query(Lead).filter(Lead.id == lead_id).first()
                            if lead and lead.contact_id:
                                contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
                                contact_email = contact.email if contact else ""
                                tz = params.get("timezone")
                                if not tz:
                                    from apps.api.modules.crm.models import Company
                                    if contact and contact.company_id:
                                        company = db.query(Company).filter(Company.id == contact.company_id).first()
                                        if company and company.country:
                                            c = company.country.lower()
                                            if "india" in c or c == "in":
                                                tz = "Asia/Kolkata"
                                            elif "uk" in c or "united kingdom" in c:
                                                tz = "Europe/London"
                                            elif "us" in c or "united states" in c:
                                                tz = "America/New_York"
                                            elif "australia" in c or c == "au":
                                                tz = "Australia/Sydney"
                                    if not tz:
                                        tz = "Asia/Kolkata" # Final fallback if missing
                                        
                                import zoneinfo
                                tz_obj = zoneinfo.ZoneInfo(tz)
                                local_now = datetime.now(tz_obj)
                                local_tomorrow_10am = (local_now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                                slot_start = local_tomorrow_10am.replace(tzinfo=None)
                                slot_end = slot_start + timedelta(minutes=30)
                                
                                result = MeetingsService().book_meeting(
                                    db=db,
                                    contact_id=lead.contact_id,
                                    contact_email=contact_email,
                                    slot_start=slot_start,
                                    slot_end=slot_end,
                                    title="Agent-Initiated — SETV AI Platform",
                                    description="Auto-booked by AgentController",
                                    lead_id=lead_id,
                                    timezone=tz
                                )
                                db.flush()
                                outcome = {"status": "executed", **(result or {})}
                            else:
                                outcome = {"status": "skipped", "reason": "No lead or contact found"}
                        else:
                            outcome = {"status": "skipped", "reason": "No lead_id for meeting booking"}
                    else:
                        outcome = {"status": "pending_approval", "action": action, "params": params}

                else:
                    outcome = {"status": "skipped", "reason": f"Unknown action: {action}"}

            except Exception as exc:
                logger.error("[AgentController.act] Action %s failed: %s", action, exc, exc_info=True)
                outcome = {"status": "failed", "error": str(exc)}

            outcomes.append(outcome)



        return outcomes

    # ─── log_decision ─────────────────────────────────────────────────────────

    def log_decision(
        self,
        db: Session,
        cycle_id: str,
        goal: AgentGoal,
        state: dict,
        action: str,
        params: dict,
        reasoning: str,
        status: str,
        outcome: dict,
    ) -> AgentDecision:
        """Write one AgentDecision row. Called for every tool call in a cycle."""
        decision = AgentDecision(
            cycle_id=cycle_id,
            goal_snapshot=json.dumps({
                "target_metric": goal.target_metric,
                "target_value": goal.target_value,
                "period": goal.period,
            }),
            state_snapshot=json.dumps(state, default=str),
            chosen_action=action,
            action_params=json.dumps(params),
            reasoning=reasoning,
            status=status,
            outcome=json.dumps(outcome, default=str),
            executed_at=datetime.now(timezone.utc) if status in ("executed", "skipped") else None,
        )
        db.add(decision)
        db.flush()
        return decision

    # ─── reflect ──────────────────────────────────────────────────────────────

    def reflect(self, db: Session, cycle_id: str, tool_calls: list[dict], outcomes: list[dict]):
        """
        After a cycle, distill a short lesson from decisions + outcomes.
        Stores the lesson in agent_reflections with structured JSON tags.
        This is what makes future decide() calls smarter — not just a history log.
        """
        if not tool_calls:
            return

        episodes_text = ""
        for tc, outcome in zip(tool_calls, outcomes):
            # Include template selection context in the reflection prompt if available
            template_ctx = ""
            if tc.get("_template_name"):
                conf = tc.get("_template_confidence")
                template_ctx = f"\nTemplate Selected: {tc['_template_name']}"
                if conf is not None:
                    template_ctx += f" (confidence: {conf:.0%})"
                if tc.get("_template_reasoning"):
                    template_ctx += f"\nTemplate Reasoning: {tc['_template_reasoning']}"
            episodes_text += f"\nAction: {tc.get('action')}{template_ctx}\nReasoning: {tc.get('reasoning', '')}\nOutcome: {json.dumps(outcome, default=str)}\n---"

        prompt = f"""Cycle ID: {cycle_id}

Episodes this cycle:
{episodes_text}

Write a short distilled lesson from this cycle (1-2 sentences max).
Focus on what worked, what failed, and what to do differently."""

        try:
            result = AIProvider().generate_content(
                system_instruction=REFLECTION_SYSTEM,
                prompt=prompt,
            )
            lesson = result.get("lesson", "")
            raw_tags = result.get("tags", {})

            if not lesson:
                return

            # Ensure tags are structured JSON with known keys only
            # template_name is a first-class tag now for template-aware retrieval
            tags = {
                k: v for k, v in raw_tags.items()
                if k in ("template_name", "template_hash", "provider", "segment", "lead_id") and v is not None
            }

            reflection = AgentReflection(
                lesson=lesson,
                tags=json.dumps(tags),
                episode_cycle_ids=json.dumps([cycle_id]),
            )
            db.add(reflection)
            db.commit()
            logger.info("[AgentController.reflect] Lesson: %s", lesson[:100])

        except Exception as exc:
            logger.warning("[AgentController.reflect] Failed to write reflection: %s", exc)

    # ─── Private helpers ───────────────────────────────────────────────────────

    def _get_or_create_goal(self, db: Session) -> AgentGoal:
        """Return the singleton AgentGoal row, creating defaults if absent."""
        goal = db.query(AgentGoal).first()
        if not goal:
            goal = AgentGoal()
            db.add(goal)
            db.commit()
            db.refresh(goal)
        return goal

    def _measure_goal_progress(self, db: Session, metric: str, period_start: datetime) -> int:
        """Count how many of the target metric have been achieved this period."""
        if metric == "meetings_booked":
            return db.query(Meeting).filter(Meeting.created_at >= period_start).count()
        elif metric == "leads_qualified":
            return db.query(Lead).filter(
                Lead.status.in_(["scored", "contacted", "replied", "meeting_booked"]),
                Lead.stage_entered_at >= period_start,
            ).count()
        elif metric == "leads_persisted":
            return db.query(Lead).filter(Lead.created_at >= period_start).count()
        elif metric == "replies_received":
            return db.query(Email).filter(
                Email.replied_at != None,
                Email.replied_at >= period_start,
            ).count()
        return 0

    def _get_relevant_reflections(self, db: Session, state: dict) -> list[str]:
        """
        Retrieve reflections whose tags are relevant to the current state.
        Keeps the decide() prompt small by not including every reflection ever written.
        Now also matches on template_name tags for template-aware learning.
        """
        relevant: list[str] = []

        # Build a set of tags present in the current state
        active_tags: dict = {}
        uv = state.get("outreach", {}).get("underperforming_variant")
        if uv:
            active_tags["template_hash"] = uv.get("subject_snippet", "")[:20]

        provider_health = state.get("provider_health", {})
        for provider in provider_health:
            active_tags["provider"] = provider

        # Match on template names present in current template stats
        template_stats = state.get("outreach", {}).get("template_stats", {})
        for tname in template_stats:
            active_tags["template_name"] = tname

        reflections = (
            db.query(AgentReflection)
            .order_by(AgentReflection.created_at.desc())
            .limit(30)
            .all()
        )

        matched_reflections = []
        recent_reflections = []

        for ref in reflections:
            try:
                tags = json.loads(ref.tags or "{}")
            except Exception:
                tags = {}

            match = False
            for key, val in active_tags.items():
                if tags.get(key) and val and str(tags.get(key))[:20] == str(val)[:20]:
                    match = True
                    break

            if match:
                matched_reflections.append(ref.lesson)
            elif len(recent_reflections) < 5:
                recent_reflections.append(ref.lesson)

        # Prioritize matches, then fill with recent general lessons up to a limit
        relevant = matched_reflections + [r for r in recent_reflections if r not in matched_reflections]
        
        return relevant[:10]

    def _select_outreach_template(self, db: Session, goal: AgentGoal, settings, state: dict, reflections: list[str]) -> dict:
        """
        Select the best outreach template according to the agent's outreach strategy.

        Returns a dict: {template_id, template_name, reasoning, confidence}

        Strategies:
          fixed     → use settings.default_outreach_template_id directly
          rotate    → cycle through available templates using email count as a clock
          ai_select → call LLM with goal + performance data + reflections
        """
        strategy = getattr(goal, 'outreach_strategy', 'fixed') or 'fixed'
        available = state.get("outreach", {}).get("available_templates", [])
        template_stats = state.get("outreach", {}).get("template_stats", {})

        # ── Fixed: use the designated default ────────────────────────────────
        if strategy == "fixed":
            tid = getattr(settings, 'default_outreach_template_id', None)
            if tid:
                from apps.api.modules.crm.models import OutreachTemplate
                t = db.query(OutreachTemplate).filter(OutreachTemplate.id == tid).first()
                if t:
                    return {
                        "template_id": t.id,
                        "template_name": t.name,
                        "reasoning": f"Fixed strategy: always use the designated default template '{t.name}'.",
                        "confidence": 1.0,
                    }
            return {"template_id": None, "template_name": "AI Generated", "reasoning": "No default template set; AI will generate freely.", "confidence": 0.5}

        # ── Rotate: cycle through all templates sequentially ──────────────────
        if strategy == "rotate" and available:
            total_emails = state.get("outreach", {}).get("total_sent_period", 0)
            idx = total_emails % len(available)
            chosen = available[idx]
            return {
                "template_id": chosen["id"],
                "template_name": chosen["name"],
                "reasoning": f"Rotate strategy: cycling through templates sequentially. Using '{chosen['name']}' (position {idx + 1} of {len(available)}).",
                "confidence": 0.75,
            }

        # ── AI Select: LLM-driven selection ───────────────────────────────────
        if strategy == "ai_select" and available:
            # Format performance data concisely for the prompt
            perf_lines = []
            for tname, stats in template_stats.items():
                perf_lines.append(f"  - {tname}: {stats['sent']} sent, {stats['replied']} replies ({stats['reply_rate']:.1%} reply rate)")
            perf_block = "\n".join(perf_lines) if perf_lines else "  No performance data yet."

            reflection_block = ""
            if reflections:
                reflection_block = "Past lessons from Agent Memory:\n" + "\n".join(f"  • {r}" for r in reflections[:5])

            template_list = "\n".join(f"  - id={t['id']}, name={t['name']}, category={t.get('category', 'general')}" for t in available)

            prompt = f"""Current Goal: {goal.target_metric} (target: {goal.target_value})

Available Templates:
{template_list}

Template Performance (last 30 days):
{perf_block}

{reflection_block}

Select the single best template for the next outreach batch."""

            try:
                result = AIProvider().generate_content(
                    system_instruction=TEMPLATE_SELECT_SYSTEM,
                    prompt=prompt,
                )
                template_id = result.get("template_id")
                template_name = result.get("template_name", "AI Generated")
                reasoning = result.get("reasoning", "AI selected based on goal and performance.")
                confidence = float(result.get("confidence", 0.7))

                # Validate template_id is real
                if template_id:
                    valid = any(t["id"] == template_id for t in available)
                    if not valid:
                        template_id = None

                logger.info("[AgentController._select_outreach_template] AI selected: %s (confidence=%.0f%%)", template_name, confidence * 100)
                return {"template_id": template_id, "template_name": template_name, "reasoning": reasoning, "confidence": confidence}

            except Exception as exc:
                logger.warning("[AgentController._select_outreach_template] LLM failed, falling back to best performer: %s", exc)
                # Fallback: pick template with highest reply rate from stats
                if template_stats:
                    best_name = max(template_stats, key=lambda k: template_stats[k]["reply_rate"])
                    best_tid = template_stats[best_name].get("template_id")
                    return {
                        "template_id": best_tid,
                        "template_name": best_name,
                        "reasoning": f"Fallback: '{best_name}' has the highest historical reply rate ({template_stats[best_name]['reply_rate']:.1%}).",
                        "confidence": 0.6,
                    }

        # Last resort: no template (AI generates freely)
        return {"template_id": None, "template_name": "AI Generated", "reasoning": "No templates available; AI will generate email content freely.", "confidence": 0.4}

    def _revise_template(self, params: dict) -> dict:
        """
        Call the LLM to produce a revised outreach subject + body.
        Stores the result in the AgentDecision outcome (not a separate table).
        The revised prompt can be used on the next outreach call for that segment.
        """
        subject_snippet = params.get("subject_snippet", "")
        reply_rate = params.get("reply_rate", 0.0)
        sample_size = params.get("sample_size", params.get("sends", 0))

        revision_system = """You are revising an outreach email subject and opening for SETV, a healthcare B2B sales platform.
The current subject line is underperforming. Generate an improved version.
Return JSON: {"new_subject": str, "new_body_opening": str, "rationale": str}
Keep the subject under 60 characters. Keep the opening under 3 sentences."""

        prompt = f"""Current subject snippet: "{subject_snippet}"
Reply rate: {reply_rate:.1%} over {sample_size} sends (below target threshold).

Diagnose why this is underperforming and write an improved subject line and email opening.
Focus on specificity, relevance to healthcare decision-makers, and a clear value hook."""

        try:
            result = AIProvider().generate_content(
                system_instruction=revision_system,
                prompt=prompt,
            )
            return {
                "new_subject": result.get("new_subject", ""),
                "new_body_opening": result.get("new_body_opening", ""),
                "rationale": result.get("rationale", ""),
                "original_subject_snippet": subject_snippet,
                "original_reply_rate": reply_rate,
                "prompt_version": str(datetime.now(timezone.utc).date()),
            }
        except Exception as exc:
            logger.error("[AgentController._revise_template] Failed: %s", exc)
            return {"error": str(exc), "outcome": "provider_error"}

    # ─── Public helper for manual decision approval ────────────────────────────

    def execute_pending_decision(self, db: Session, decision_id: int) -> dict:
        """
        Called by POST /orchestration/agent/decisions/{id}/approve.
        Executes a pending_approval decision and marks it as approved+executed.
        Bug 1 fix: passes force=True so act() bypasses the autonomy flag that
        caused the action to be deferred in the first place.
        """
        decision = db.query(AgentDecision).filter(AgentDecision.id == decision_id).first()
        if not decision:
            return {"error": "Decision not found"}
        if decision.status != "pending_approval":
            return {"error": f"Decision is already in status '{decision.status}'"}

        goal = self._get_or_create_goal(db)
        settings = db.query(AgentSettings).first()
        if not settings:
            settings = AgentSettings()
            db.add(settings)
            db.commit()

        try:
            params = json.loads(decision.action_params or "{}")
        except Exception:
            params = {}

        dummy_state = json.loads(decision.state_snapshot or "{}")
        # force=True bypasses all autonomy flag checks — the human just approved it
        outcomes = self.act(
            db=db,
            tool_calls=[{"action": decision.chosen_action, "params": params, "reasoning": decision.reasoning}],
            goal=goal,
            settings=settings,
            cycle_id=decision.cycle_id,
            state=dummy_state,
            force=True,
        )
        outcome = outcomes[0] if outcomes else {}

        decision.status = "executed"
        decision.outcome = json.dumps(outcome, default=str)
        decision.executed_at = datetime.now(timezone.utc)
        db.flush()

        return {"decision_id": decision_id, "status": "approved", "outcome": outcome}

    # ─── Revision helpers (Bug 3) ──────────────────────────────────────────────

    def _save_active_revision(self, goal: AgentGoal, db: Session, revision: dict) -> None:
        """
        Persist an approved template revision on the AgentGoal row so future
        outreach calls can consult it.
        Stored as JSON in active_revision_json (additive column).
        """
        try:
            import json as _json
            payload = {
                "new_subject": revision.get("new_subject", ""),
                "new_body_opening": revision.get("new_body_opening", ""),
                "rationale": revision.get("rationale", ""),
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
            goal.active_revision_json = _json.dumps(payload)
            db.flush()
            logger.info("[AgentController] Active revision saved: %s", revision.get("new_subject", "")[:60])
        except Exception as exc:
            logger.warning("[AgentController] Failed to save active revision: %s", exc)

    def _get_active_revision_hint(self, goal: AgentGoal) -> str:
        """
        Return a concise guidance string from the most recently approved revision,
        or empty string if none exists.  Passed into OutreachService.generate_initial_outreach()
        as the revision_hint parameter so the LLM prompt can use it.
        """
        try:
            if not getattr(goal, "active_revision_json", None):
                return ""
            import json as _json
            rev = _json.loads(goal.active_revision_json)
            parts = []
            if rev.get("new_subject"):
                parts.append(f"Preferred subject line style: {rev['new_subject']}")
            if rev.get("new_body_opening"):
                parts.append(f"Preferred opening approach: {rev['new_body_opening']}")
            if rev.get("rationale"):
                parts.append(f"Rationale: {rev['rationale']}")
            return "\n".join(parts) if parts else ""
        except Exception:
            return ""
