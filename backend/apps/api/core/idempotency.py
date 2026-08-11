"""
Idempotency protection for scheduled jobs.

Each scheduled job (signal scan, inbox poll, follow-up outreach) generates a
composite key like "signal_scan:lead_42:2026-07-14". Before doing work, the job
calls check_and_mark(). If the key already exists → skip. Otherwise → insert
the key and proceed.
"""

from sqlalchemy import Column, Integer, String, DateTime, UniqueConstraint
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from apps.api.db.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String, nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)
    window_key = Column(String, nullable=False)
    created_at = Column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("job_type", "entity_id", "window_key", name="uq_idempotency"),
    )


def check_and_mark(db: Session, job_type: str, entity_id: str, window_key: str) -> bool:
    """
    Returns True if this job+entity+window was already processed (caller should SKIP).
    Returns False if it's new — inserts the record so future calls will skip.
    """
    existing = (
        db.query(IdempotencyRecord)
        .filter(
            IdempotencyRecord.job_type == job_type,
            IdempotencyRecord.entity_id == entity_id,
            IdempotencyRecord.window_key == window_key,
        )
        .first()
    )
    if existing:
        return True

    record = IdempotencyRecord(
        job_type=job_type,
        entity_id=entity_id,
        window_key=window_key,
    )
    db.add(record)
    db.flush()
    return False
