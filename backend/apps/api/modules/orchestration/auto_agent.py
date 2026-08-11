import logging
import json
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from apps.api.db.database import SessionLocal
from apps.api.modules.crm.models import AgentSettings, JobTemplate, Lead
from apps.api.modules.prospecting.models import ProspectingJob
from apps.api.modules.prospecting.schemas import ProspectingRequest
from apps.api.modules.prospecting.service import ProspectingService
from apps.api.modules.signals.service import SignalsService
from apps.api.modules.outreach.service import OutreachService
from apps.api.modules.email.service import EmailService

logger = logging.getLogger(__name__)

class AutoAgentRunner:
    def __init__(self):
        self.prospecting = ProspectingService()
        self.signals = SignalsService()
        self.outreach = OutreachService()

    def run_pipeline(self):
        """
        Executes the autonomous agent pipeline.
        This is called by the APScheduler interval job.
        """
        db = SessionLocal()
        job = None
        logs = []
        settings = None

        def log_step(msg: str):
            logger.info(f"[AutoAgent] {msg}")
            logs.append(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}")

        try:
            settings = db.query(AgentSettings).first()
            if not settings:
                settings = AgentSettings()
                db.add(settings)
                db.commit()

            if not settings.enabled:
                return

            now = datetime.utcnow()
            
            # Wait for interval unless next_run is None
            if settings.next_run and settings.next_run > now:
                return

            if settings.current_status == "Running":
                log_step("Agent is already running. Skipping this interval.")
                return

            settings.current_status = "Running"
            settings.current_stage = "Initializing"
            settings.last_run = now
            db.commit()

            # Create Job History
            job = ProspectingJob(status="Running", started_at=now)
            db.add(job)
            db.commit()

            log_step("Starting Autonomous Pipeline...")

            # ── 1. Discover Companies ─────────────────────────────────────────────
            settings.current_stage = "Discovering Leads"
            db.commit()

            template = None
            if settings.default_template_id:
                template = db.query(JobTemplate).filter(JobTemplate.id == settings.default_template_id).first()
            
            if not template:
                from sqlalchemy.sql.expression import func
                template = db.query(JobTemplate).order_by(func.random()).first()
                if template:
                    log_step("No default template set. Rotating to random template.")

            if template:
                job.template_used_id = template.id
                db.commit()
                
                keywords_str = f"{template.keywords or ''}, {template.technologies or ''}".strip(', ')
                kw_list = [k.strip() for k in keywords_str.split(',')] if keywords_str else []
                
                req = ProspectingRequest(
                    region=template.regions or "US", 
                    industry=template.industries or "Healthcare",
                    keywords=kw_list,
                )
                
                log_step(f"Running Prospecting with Template: {template.name}")
                try:
                    result = self.prospecting.discover_leads(db, req)
                    
                    job.total_leads_persisted += len(result.leads)
                    job.total_companies_discovered += len(set([l.company_id for l in result.leads if hasattr(l, 'company_id')]))
                    db.commit()
                    log_step(f"Prospecting found {len(result.leads)} new leads.")
                except Exception as e:
                    log_step(f"ERROR: Prospecting failed: {str(e)}")
            else:
                log_step("No valid default template found. Skipping Prospecting.")

            # ── 2. Signal Scan & Scoring ──────────────────────────────────────────
            settings.current_stage = "Enriching & Scoring"
            db.commit()

            new_leads = db.query(Lead).filter(Lead.status == "new").limit(settings.max_leads_per_run).all()
            scored_count = 0
            if new_leads:
                log_step(f"Scanning signals for {len(new_leads)} new leads...")
                for lead in new_leads:
                    try:
                        res = self.signals.scan_lead_signals(db, lead.id)
                        if not res.get("skipped"):
                            scored_count += 1
                    except Exception as e:
                        log_step(f"ERROR: Failed to scan signals for lead {lead.id}: {str(e)}")
                        break # Stop processing new leads this run to respect rate limits
                
                job.total_leads_qualified += scored_count
                db.commit()
                log_step(f"Enriched and scored {scored_count} leads.")
            else:
                log_step("No new leads to score.")

            # ── 3. Generate Outreach ──────────────────────────────────────────────
            settings.current_stage = "Generating Outreach"
            db.commit()

            # Find high-score leads that haven't been contacted yet
            qualified_leads = db.query(Lead).filter(
                Lead.status == "scored",
                Lead.lead_score >= 70  # arbitrary threshold for auto-outreach
            ).limit(settings.max_leads_per_run).all()

            generated_count = 0
            if qualified_leads:
                log_step(f"Generating outreach for {len(qualified_leads)} qualified leads...")
                for lead in qualified_leads:
                    sig_summary = f"Lead score: {lead.lead_score}, Priority: {lead.priority}"
                    try:
                        res = self.outreach.generate_initial_outreach(db, lead.id, signal_summary=sig_summary)
                        if not res.get("skipped"):
                            generated_count += 1
                            
                            # Auto-send if enabled
                            if settings.auto_send_emails:
                                try:
                                    email_id = res.get("email_id")
                                    if email_id:
                                        email_svc = EmailService(db)
                                        email_svc.send_email_by_id(email_id)
                                        job.emails_sent += 1
                                        log_step(f"Auto-sent email #{email_id} to Lead #{lead.id}")
                                except Exception as e:
                                    log_step(f"Failed to auto-send email for lead {lead.id}: {str(e)}")
                    except Exception as e:
                        log_step(f"ERROR: Failed to generate outreach for lead {lead.id}: {str(e)}")
                        break # Stop generating to respect rate limits

                job.outreach_generated += generated_count
                db.commit()
                log_step(f"Generated {generated_count} outreach emails.")
            else:
                log_step("No highly qualified leads ready for outreach.")

            # ── 4. Process Replies ────────────────────────────────────────────────
            settings.current_stage = "Monitoring Replies"
            db.commit()

            if settings.reply_monitoring:
                log_step("Fetching incoming replies...")
                try:
                    email_svc = EmailService(db)
                    replies = email_svc.fetch_incoming_replies()
                    log_step(f"Processed {len(replies)} new replies.")
                except Exception as e:
                    log_step(f"ERROR: Failed to fetch replies: {str(e)}")

            # ── Finalize ─────────────────────────────────────────────────────────
            log_step("Pipeline execution completed successfully.")
            
            job.status = "Completed"
            job.completed_at = datetime.utcnow()
            
            settings.current_status = "Idle"
            settings.current_stage = None
            settings.next_run = datetime.utcnow() + timedelta(minutes=settings.interval_minutes)

        except Exception as e:
            logger.error(f"AutoAgent Pipeline Error: {e}", exc_info=True)
            log_step(f"ERROR: {str(e)}")
            if job:
                job.status = "Error"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
            
            # Don't keep the agent stuck in "Running" forever
            if settings:
                settings.current_status = "Error"
                settings.current_stage = None
                settings.next_run = datetime.utcnow() + timedelta(minutes=settings.interval_minutes)
        finally:
            if job:
                job.execution_logs = json.dumps(logs)
            db.commit()
            db.close()
