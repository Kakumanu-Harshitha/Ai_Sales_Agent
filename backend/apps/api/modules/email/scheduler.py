"""
DEPRECATED: Email-specific scheduler has been replaced by the centralized
scheduler at apps.api.core.scheduler.

This file is kept as a no-op stub so existing imports don't break.
The inbox_poll_job now runs from core/scheduler.py alongside
signal_scan_job and followup_outreach_job.
"""

import logging

logger = logging.getLogger(__name__)


def start_scheduler():
    """No-op. Scheduler is now centralized in core/scheduler.py."""
    logger.info("email/scheduler.py start_scheduler() called — this is a no-op. "
                "Scheduler is centralized in core/scheduler.py.")
