"""
Agent Controller — Database Models

New tables supporting the goal-directed AgentController:
  agent_goals        — what the agent is trying to achieve + autonomy dial flags
  agent_decisions    — full decision log (state snapshot, chosen action, reasoning, outcome)
  agent_reflections  — distilled lessons written after each cycle (the actual learning mechanism)

All tables are additive — no existing tables are modified.
"""

import uuid
import json
from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, Float
from datetime import datetime, timezone
from apps.api.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class AgentGoal(Base):
    """
    Defines what the agent is working toward this period.
    There is exactly one row — the controller upserts it.

    Autonomy dial flags control whether risky actions execute immediately
    or are staged as pending_approval decisions for human review.
    """
    __tablename__ = "agent_goals"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # ── Goal ──────────────────────────────────────────────────────────────────
    target_metric = Column(String, default="meetings_booked")
    # "meetings_booked" | "leads_qualified" | "replies_received"
    target_value = Column(Integer, default=10)
    period = Column(String, default="weekly")  # "weekly" | "daily"



    # ── Revision thresholds ───────────────────────────────────────────────────
    min_sample_for_revision = Column(Integer, default=5)   # min sends before revise_template fires
    reply_rate_floor = Column(Float, default=0.05)         # below this rate, revision triggers
    reflect_every_n_cycles = Column(Integer, default=1)    # write a reflection every N cycles
    cycles_since_last_reflection = Column(Integer, default=0)

    # ── Autonomy dial ─────────────────────────────────────────────────────────
    # Safe / reversible — always autonomous
    auto_rescan_signals = Column(Boolean, default=True)
    auto_re_enrich_lead = Column(Boolean, default=True)

    # Risky — start in propose-wait-for-approval mode
    auto_revise_template = Column(Boolean, default=False)
    # NOTE: auto_send_email is NOT here — AgentSettings.auto_send_emails is the single source of truth
    auto_book_meeting = Column(Boolean, default=False)

    # ── Outreach Strategy ────────────────────────────────────────────────────
    # Controls how the controller selects the outreach template each cycle.
    # "fixed"     → always use AgentSettings.default_outreach_template_id
    # "rotate"    → cycle through available templates sequentially
    # "ai_select" → LLM picks the best template based on goal + memory + performance
    outreach_strategy = Column(String, default="fixed")

    # ── Active revision (Bug 3 fix) ────────────────────────────────────────────
    # Stores the last approved revise_template output as JSON so OutreachService
    # can consult it when composing the next outreach email.
    # Schema: {"new_subject": str, "new_body_opening": str, "rationale": str, "approved_at": str}
    active_revision_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)


class AgentDecision(Base):
    """
    Full audit log of every decision made by the AgentController.

    Each run_cycle produces one or more AgentDecision rows grouped by cycle_id.
    This is the table you read out loud in the demo to show "why the agent did X".

    status values:
      pending_approval  — action proposed but not yet executed (autonomy flag is False)
      executed          — action ran successfully
      approved          — pending_approval manually approved and executed
      skipped           — agent chose do_nothing_this_cycle
      failed            — action attempted but raised an error
    """
    __tablename__ = "agent_decisions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # Identifies all decisions within one run_cycle() call
    cycle_id = Column(String, default=new_uuid, index=True)

    # Full snapshot of goal + state at decision time (JSON)
    goal_snapshot = Column(Text, nullable=True)
    state_snapshot = Column(Text, nullable=True)

    # What the agent decided
    chosen_action = Column(String, nullable=False)
    # tool names: discover_more_leads | rescan_signals | re_enrich_lead |
    #             send_initial_outreach | send_followup | revise_template | do_nothing_this_cycle
    action_params = Column(Text, nullable=True)  # JSON
    reasoning = Column(Text, nullable=True)      # LLM's stated reason

    # Execution
    status = Column(String, default="pending_approval")  # see docstring
    outcome = Column(Text, nullable=True)  # JSON, filled in after execution
    # For revise_template this contains: {"new_subject": ..., "new_body": ..., "rationale": ...}
    # For provider calls this contains: {"provider": ..., "found": bool, "outcome": "success|rate_limited|provider_error"}
    error_detail = Column(Text, nullable=True)

    # Link to the reflection that was derived from this decision (if any)
    reflection_id = Column(Integer, nullable=True)

    created_at = Column(DateTime, default=utcnow, index=True)
    executed_at = Column(DateTime, nullable=True)


class AgentReflection(Base):
    """
    Short, distilled lessons written by the controller after reviewing episode outcomes.

    This is the difference between "the agent noticed a low reply rate" (fact in AgentDecision)
    and "the agent has a standing opinion about why, and acts on it next time without
    re-deriving it from scratch" (a reflection, retrieved and injected into decide()).

    tags is a JSON object with structured keys so retrieval stays reliable:
      {"template_hash": "abc123", "provider": "hunter", "segment": "high_score", "lead_id": 42}

    Not all keys need to be present — only the ones relevant to this lesson.
    """
    __tablename__ = "agent_reflections"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    lesson = Column(Text, nullable=False)  # 1-2 sentence distilled lesson
    tags = Column(Text, nullable=True)     # JSON object with structured keys (see docstring)

    # Which cycle_ids this reflection was derived from
    episode_cycle_ids = Column(Text, nullable=True)  # JSON list of cycle_id strings

    created_at = Column(DateTime, default=utcnow, index=True)
