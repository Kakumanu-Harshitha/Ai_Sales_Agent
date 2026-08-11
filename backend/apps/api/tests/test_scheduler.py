"""
Tests for Jules Prompt 2.5:
- Idempotent scheduled processing (signal scan, inbox poll, follow-up outreach)
- Pipeline report structure and correctness

Uses SQLite in-memory for fast, isolated testing.
"""

import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from apps.api.db.database import Base
from apps.api.core.idempotency import IdempotencyRecord, check_and_mark
from apps.api.modules.crm.models import (
    Company, Contact, Lead, Signal, LeadScore,
    Email, Activity, Meeting, Campaign, Reply,
)


# ── Test DB Setup ────────────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite:///./test_scheduler.db"
engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    """Create all tables before each test, drop after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _create_test_lead(db, status="new", deal_value=None, days_since_activity=0):
    """Helper: create a company → contact → lead chain."""
    import uuid
    uid = uuid.uuid4().hex[:8]

    company = Company(name=f"TestCo-{uid}", domain=f"{uid}.example.com")
    db.add(company)
    db.flush()

    contact = Contact(
        company_id=company.id,
        first_name="Test",
        last_name=f"User-{uid}",
        email=f"{uid}@example.com",
    )
    db.add(contact)
    db.flush()

    activity_time = datetime.now(timezone.utc) - timedelta(days=days_since_activity)
    lead = Lead(
        contact_id=contact.id,
        status=status,
        deal_value=deal_value,
        stage_entered_at=activity_time,
        last_activity_at=activity_time,
    )
    db.add(lead)
    db.flush()

    # Create immutable timeline event
    activity = Activity(
        lead_id=lead.id,
        type="Lead Created",
        description=f"Lead created with status {status}",
    )
    db.add(activity)
    db.commit()

    return lead


# ══════════════════════════════════════════════════════════════════════════
# TEST 1: Signal Scan Idempotency
# ══════════════════════════════════════════════════════════════════════════

class TestSignalScanIdempotency:

    def test_first_scan_creates_signals(self, db):
        """First signal scan for a lead should create signals and score."""
        lead = _create_test_lead(db, status="new")

        from apps.api.modules.signals.service import SignalsService
        svc = SignalsService()
        result = svc.scan_lead_signals(db, lead.id)
        db.commit()

        assert result["skipped"] is False
        assert result["signals_created"] >= 1
        assert result["score"] > 0

        # Verify signals were stored
        signals = db.query(Signal).filter(Signal.lead_id == lead.id).all()
        assert len(signals) >= 1

        # Verify lead score was stored
        scores = db.query(LeadScore).filter(LeadScore.lead_id == lead.id).all()
        assert len(scores) >= 1

        # Verify activity was created
        activities = (
            db.query(Activity)
            .filter(Activity.lead_id == lead.id, Activity.type == "Signals Detected")
            .all()
        )
        assert len(activities) == 1

    def test_second_scan_same_day_is_skipped(self, db):
        """Running signal scan twice for the same lead on the same day should skip."""
        lead = _create_test_lead(db, status="new")

        from apps.api.modules.signals.service import SignalsService
        svc = SignalsService()

        # First scan
        result1 = svc.scan_lead_signals(db, lead.id)
        db.commit()
        assert result1["skipped"] is False

        # Second scan — should be idempotent
        result2 = svc.scan_lead_signals(db, lead.id)
        db.commit()
        assert result2["skipped"] is True

        # Verify only one set of signals exists
        signals = db.query(Signal).filter(Signal.lead_id == lead.id).all()
        assert len(signals) == 1  # Only from the first scan

    def test_scan_updates_lead_status(self, db):
        """Signal scan should promote lead from 'new' to 'scored'."""
        lead = _create_test_lead(db, status="new")

        from apps.api.modules.signals.service import SignalsService
        svc = SignalsService()
        svc.scan_lead_signals(db, lead.id)
        db.commit()
        db.refresh(lead)

        assert lead.status == "scored"
        assert lead.lead_score is not None


# ══════════════════════════════════════════════════════════════════════════
# TEST 2: Inbox Poll Idempotency
# ══════════════════════════════════════════════════════════════════════════

class TestInboxPollIdempotency:

    def test_duplicate_message_id_not_stored(self, db):
        """Processing the same message_id twice should not create duplicate replies."""
        lead = _create_test_lead(db, status="contacted")

        # Simulate first reply
        reply1 = Reply(
            lead_id=lead.id,
            message_id="unique-msg-id-123",
            content="I'm interested in your product.",
            processed=False,
        )
        db.add(reply1)
        db.commit()

        # Attempt to add same message_id — should fail due to unique constraint
        reply2 = Reply(
            lead_id=lead.id,
            message_id="unique-msg-id-123",
            content="Duplicate content.",
            processed=False,
        )
        db.add(reply2)

        with pytest.raises(Exception):
            db.commit()

        db.rollback()

        # Verify only one reply exists
        replies = db.query(Reply).filter(Reply.message_id == "unique-msg-id-123").all()
        assert len(replies) == 1


# ══════════════════════════════════════════════════════════════════════════
# TEST 3: Follow-Up Outreach Idempotency
# ══════════════════════════════════════════════════════════════════════════

class TestFollowUpIdempotency:

    def test_followup_generated_for_stale_lead(self, db):
        """A lead with no activity for 3+ days should get a follow-up."""
        lead = _create_test_lead(db, status="contacted", days_since_activity=5)

        from apps.api.modules.outreach.service import OutreachService
        svc = OutreachService()
        result = svc.generate_followup(db, lead.id)
        db.commit()

        assert result["skipped"] is False
        assert result["email_id"] is not None

        # Verify email was created
        emails = db.query(Email).filter(Email.lead_id == lead.id).all()
        assert len(emails) == 1

        # Verify activity was created
        activities = (
            db.query(Activity)
            .filter(
                Activity.lead_id == lead.id,
                Activity.type == "Follow-up Outreach Generated",
            )
            .all()
        )
        assert len(activities) == 1

    def test_duplicate_followup_is_skipped(self, db):
        """Running follow-up twice for the same lead + step + day should skip."""
        lead = _create_test_lead(db, status="contacted", days_since_activity=5)

        from apps.api.modules.outreach.service import OutreachService
        svc = OutreachService()

        # First follow-up
        result1 = svc.generate_followup(db, lead.id)
        db.commit()
        assert result1["skipped"] is False

        # Second follow-up — should be idempotent
        result2 = svc.generate_followup(db, lead.id)
        db.commit()
        assert result2["skipped"] is True

        # Verify only one email exists
        emails = db.query(Email).filter(Email.lead_id == lead.id).all()
        assert len(emails) == 1


# ══════════════════════════════════════════════════════════════════════════
# TEST 4: Idempotency Record System
# ══════════════════════════════════════════════════════════════════════════

class TestIdempotencySystem:

    def test_check_and_mark_first_call_returns_false(self, db):
        """First call to check_and_mark should return False (proceed)."""
        result = check_and_mark(db, "test_job", "entity_1", "2026-07-14")
        db.commit()
        assert result is False

    def test_check_and_mark_second_call_returns_true(self, db):
        """Second call with same key should return True (skip)."""
        check_and_mark(db, "test_job", "entity_1", "2026-07-14")
        db.commit()

        result = check_and_mark(db, "test_job", "entity_1", "2026-07-14")
        assert result is True

    def test_different_window_key_allows_reprocessing(self, db):
        """Different window key (e.g., next day) should allow reprocessing."""
        check_and_mark(db, "test_job", "entity_1", "2026-07-14")
        db.commit()

        result = check_and_mark(db, "test_job", "entity_1", "2026-07-15")
        db.commit()
        assert result is False

    def test_different_entity_is_independent(self, db):
        """Different entity_id should be independent."""
        check_and_mark(db, "test_job", "entity_1", "2026-07-14")
        db.commit()

        result = check_and_mark(db, "test_job", "entity_2", "2026-07-14")
        db.commit()
        assert result is False


# ══════════════════════════════════════════════════════════════════════════
# TEST 5: Pipeline Report Structure
# ══════════════════════════════════════════════════════════════════════════

class TestPipelineReport:

    def test_empty_pipeline_report(self, db):
        """Pipeline report on empty DB should return valid structure with zeros."""
        from apps.api.modules.pipeline.service import PipelineService
        svc = PipelineService()
        report = svc.generate_report(db)

        assert report.lead_funnel.new == 0
        assert report.lead_funnel.closed_won == 0
        assert report.pipeline_forecast.total_value == 0.0
        assert report.revenue_forecast.expected_revenue == 0.0
        assert isinstance(report.risk_flags, list)
        assert isinstance(report.stalled_deals, list)
        assert report.campaign_performance.sent == 0
        assert isinstance(report.next_best_actions, list)
        assert len(report.next_best_actions) > 0  # Should have at least "pipeline is empty"

    def test_pipeline_report_with_data(self, db):
        """Pipeline report with real leads should compute correct funnel counts."""
        # Create leads in various stages
        _create_test_lead(db, status="new", deal_value=10000)
        _create_test_lead(db, status="new", deal_value=20000)
        _create_test_lead(db, status="scored", deal_value=30000)
        _create_test_lead(db, status="contacted", deal_value=50000)
        _create_test_lead(db, status="closed_won", deal_value=100000)

        from apps.api.modules.pipeline.service import PipelineService
        svc = PipelineService()
        report = svc.generate_report(db)

        assert report.lead_funnel.new == 2
        assert report.lead_funnel.scored == 1
        assert report.lead_funnel.contacted == 1
        assert report.lead_funnel.closed_won == 1
        assert report.pipeline_forecast.total_value > 0
        assert report.revenue_forecast.expected_revenue > 0

    def test_stalled_deals_detected(self, db):
        """Leads stuck in a stage >14 days should appear in stalled_deals."""
        _create_test_lead(db, status="contacted", deal_value=50000, days_since_activity=20)

        from apps.api.modules.pipeline.service import PipelineService
        svc = PipelineService()
        report = svc.generate_report(db)

        assert len(report.stalled_deals) >= 1
        assert "stuck in" in report.stalled_deals[0].lower() or "contacted" in report.stalled_deals[0].lower()

    def test_risk_flags_detected(self, db):
        """Leads with no activity >10 days should appear in risk_flags."""
        _create_test_lead(db, status="scored", deal_value=25000, days_since_activity=15)

        from apps.api.modules.pipeline.service import PipelineService
        svc = PipelineService()
        report = svc.generate_report(db)

        assert len(report.risk_flags) >= 1
        assert "no activity" in report.risk_flags[0].lower()

    def test_report_has_all_required_fields(self, db):
        """Verify report matches the schema contract exactly."""
        from apps.api.modules.pipeline.service import PipelineService
        svc = PipelineService()
        report = svc.generate_report(db)

        report_dict = report.model_dump()
        required_keys = [
            "lead_funnel", "pipeline_forecast", "revenue_forecast",
            "risk_flags", "stalled_deals", "campaign_performance",
            "conversion_rate", "next_best_actions",
        ]
        for key in required_keys:
            assert key in report_dict, f"Missing required field: {key}"
