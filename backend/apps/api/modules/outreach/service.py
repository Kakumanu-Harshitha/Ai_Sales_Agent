"""
Outreach module — business logic for AI-generated outreach + scheduled follow-ups.

Generation pipeline:
1. Load complete lead context (contact, company, signals, CRM history, intelligence)
2. Load latest SETV Knowledge Base from DB (dynamic, not hardcoded)
3. Load selected Outreach Template
4. Build rich LLM prompt
5. Call AI Provider
6. Store body (markdown/plain) as primary source of truth
7. Generate html_body dynamically via formatting pipeline
"""

import json
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from .repository import OutreachRepository
from apps.api.core.idempotency import check_and_mark
from apps.api.modules.outreach.repository import OutreachRepository
from apps.api.modules.outreach.formatting import format_and_save_email_html
from apps.api.modules.crm.models import Lead, Contact, Company, Activity, Email, Signal
from apps.api.core.ai_provider import AIProvider

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — core persona and constraints only (NO hardcoded products)
# Products/services are injected dynamically from the SETV Knowledge Base
# ──────────────────────────────────────────────────────────────────────────────

OUTREACH_SYSTEM_BASE = """You are a senior Business Development Representative at SETV Global, a healthcare AI company.
Your job is to write highly personalized, professional B2B outreach emails to healthcare decision-makers.

================================================================================
STRICT CONTENT RULES — READ BEFORE WRITING ANYTHING
================================================================================

NEVER MENTION OR REFERENCE (HARD BLOCK — ANY VIOLATION IS UNACCEPTABLE):
  ✗ API keys, environment variables, configuration files, or credentials of ANY kind
  ✗ Technical terms like OPENROUTER_API_KEY, DATABASE_URL, .env, API tokens, endpoints
  ✗ Internal software tools, agent names (Medolina, AI Agent, Sales Agent, etc.)
  ✗ Backend frameworks, databases, code, or any technical implementation
  ✗ Internal project names, repositories, or system names
  ✗ Anything from the BUYING SIGNALS section that reads like a technical log, API operation, or system event
  ✗ Invented facts, hallucinated news, fabricated events about the prospect
  ✗ Generic openers: "I hope this email finds you well", "We are pleased to...", "I wanted to reach out..."

ONLY USE FROM BUYING SIGNALS:
  ✓ Business events: expansion plans, new hospital wing, digital transformation, leadership change, funding round
  ✓ Healthcare market activities: new service line, accreditation, partnership, award
  ✓ Technology adoption signals: moving to EMR/EHR, AI interest, digital health initiative
  ✓ If a signal looks technical (mentions API, code, config, server) — IGNORE IT COMPLETELY
  ✓ If no valid business signal exists, open with a general industry observation instead

================================================================================
IDENTITY AND ROLE
================================================================================

- You are writing ON BEHALF OF SETV Global to a healthcare organization decision-maker.
- SETV is a healthcare AI company. Write as if you are a human BD rep, not an AI.
- Every email must sound hand-crafted, not automated.
- Sound like a senior enterprise sales professional — thoughtful, respectful, concise.

================================================================================
QUALITY STANDARDS
================================================================================

- Professional, warm, curiosity-inducing. NOT salesy, pushy, or generic.
- Short focused paragraphs (2-4 sentences each). One blank line between paragraphs.
- Total body length: 150-250 words (shorter for meeting requests and follow-ups).
- Every sentence must earn its place. No filler.
- The email should read like it was written specifically for this company, not copied from a template.

================================================================================
PERSONALIZATION RULES
================================================================================

- Open with the prospect's company name in the very first sentence.
- Reference at least one specific, real business detail about the company (from intelligence or signals).
- If no intelligence is available, reference the industry or org type meaningfully.
- Connect their specific situation to a SETV solution from the knowledge base.
- Do NOT fabricate or assume any information that is not explicitly provided.

================================================================================
OUTPUT FORMAT — CRITICAL
================================================================================

Return ONLY a valid JSON object with exactly these two keys:
{
  "subject": "A specific, compelling subject line mentioning the prospect company or a relevant challenge",
  "body": "Complete email body with proper paragraph breaks. NO sign-off. NO Best Regards. NO sender name."
}

- Do NOT add any text before or after the JSON.
- Do NOT use ```json or ``` code fences.
- The body MUST NOT contain: Best Regards, Warm Regards, Sincerely, or any sign-off.
- The body MUST NOT contain the sender's name, designation, company, or contact info.
- These are automatically appended by the system.
"""

# ──────────────────────────────────────────────────────────────────────────────
# PER-TEMPLATE DIRECTIVES — injected based on selected template category
# ──────────────────────────────────────────────────────────────────────────────

TEMPLATE_DIRECTIVES = {
    "Cold Outreach": """
================================================================================
TEMPLATE: COLD OUTREACH
================================================================================
OBJECTIVE: First-ever contact. Introduce SETV. Build curiosity. Get a reply.

STRUCTURE:
  1. "Dear [Name],"
  2. ONE punchy observation about their company/industry (from real data only)
  3. Bridge to a healthcare AI challenge they likely face
  4. Brief SETV intro (1-2 sentences max — do not over-explain)
  5. ONE specific SETV product or solution that fits their org type
  6. Soft CTA: "I would love to set up a brief 15-minute conversation."

TONE: Warm, professional, like a peer reaching out — not a sales pitch.
LENGTH: 130-160 words in the body.
CTA: "Would you be open to a 15-minute call this week?"
AVOID: Product feature lists. Long paragraphs. Any pressure.
""",
    "Prospecting": """
================================================================================
TEMPLATE: PROSPECTING (COLD OUTREACH)
================================================================================
OBJECTIVE: First contact. Build awareness. Earn a reply.

STRUCTURE:
  1. Specific opener referencing their company or industry context
  2. Healthcare AI challenge they are likely navigating
  3. How SETV specifically addresses that challenge
  4. Soft, non-pressuring CTA

TONE: Curious, professional, peer-to-peer.
LENGTH: 130-160 words.
CTA: "Happy to share how similar organizations are using SETV — would a brief call work?"
""",
    "Product Introduction": """
================================================================================
TEMPLATE: PRODUCT INTRODUCTION
================================================================================
OBJECTIVE: Introduce one or two specific SETV products relevant to this prospect. Explain the value clearly.

STRUCTURE:
  1. "Dear [Name],"
  2. Personalized opener referencing their company/industry
  3. Identify a specific operational challenge they likely face
  4. Introduce ONE primary SETV product that solves that challenge
  5. Use a 2-3 bullet point list for key features/benefits of that product
  6. Briefly mention a second relevant product if there is a natural fit
  7. CTA for a product walkthrough

FORMAT: Must include at least one bullet point list for product features.
TONE: Educational, confident, solution-focused.
LENGTH: 180-220 words.
CTA: "I would love to walk you through [Product Name] — would a brief demo work for you?"
""",
    "Introduction": """
================================================================================
TEMPLATE: INTRODUCTION
================================================================================
OBJECTIVE: Introduce a specific SETV product relevant to this prospect's needs.

STRUCTURE:
  1. Personalized opener
  2. Challenge identification
  3. Product intro with feature bullets
  4. Business value
  5. Demo CTA

FORMAT: Include a bullet list of 3 features.
TONE: Informative, solution-focused.
LENGTH: 180-220 words.
CTA: "Happy to show you a 20-minute walkthrough."
""",
    "Meeting Request": """
================================================================================
TEMPLATE: MEETING REQUEST
================================================================================
OBJECTIVE: Secure a calendar meeting. This email is ONLY about scheduling — nothing else.

STRUCTURE:
  1. "Dear [Name],"
  2. ONE sentence about who you are and why you are reaching out (extremely brief)
  3. ONE sentence on the specific value you will deliver in the meeting
  4. Direct ask for a time slot

TONE: Direct, respectful, concise. No fluff.
LENGTH: 80-110 words MAXIMUM. Shorter is better.
CTA: "Would Thursday or Friday work for a 20-minute call?"
AVOID: Product descriptions. Long paragraphs. Any detail that isn't needed to book the call.
""",
    "Scheduling": """
================================================================================
TEMPLATE: SCHEDULING / MEETING REQUEST
================================================================================
OBJECTIVE: Get a meeting on the calendar. Be brief and direct.

LENGTH: 80-110 words.
CTA: "Are you free for a 20-minute call this week or next?"
TONE: Respectful, direct.
AVOID: Anything unrelated to booking the meeting.
""",
    "Demo Invitation": """
================================================================================
TEMPLATE: DEMO INVITATION
================================================================================
OBJECTIVE: Invite the prospect to a live demo of SETV's platform. Create genuine excitement.

STRUCTURE:
  1. "Dear [Name],"
  2. Personalized opener — reference something specific about their organization
  3. Tease what they will SEE in the demo (3 specific demo highlights relevant to their org type)
  4. Explain the business outcome they will walk away with after the demo
  5. Low-friction CTA to book the demo

FORMAT: Use a numbered list for the 3 demo highlights.
TONE: Enthusiastic but professional. Create anticipation, not pressure.
LENGTH: 160-200 words.
CTA: "I would love to walk you through a live session — when would work best for you?"
""",
    "Demo": """
================================================================================
TEMPLATE: DEMO INVITATION
================================================================================
OBJECTIVE: Get the prospect into a product demo. Sell the demo, not the product.

STRUCTURE:
  1. Personalized opener
  2. Three specific demo highlights (as numbered list)
  3. Business outcome from attending
  4. Easy CTA to schedule

FORMAT: Numbered list of 3 demo highlights.
TONE: Enthusiastic, professional.
LENGTH: 160-200 words.
CTA: "Would you be available for a 30-minute demo session?"
""",
    "Follow-up": """
================================================================================
TEMPLATE: FOLLOW-UP
================================================================================
OBJECTIVE: Re-engage a prospect who has not replied to a previous email. Provide NEW value — not a repeat.

STRUCTURE:
  1. "Dear [Name],"
  2. Acknowledge the previous outreach very briefly (1 sentence)
  3. Lead with something NEW: a relevant industry insight, a recent SETV development, or a different angle
  4. Offer a low-commitment way to engage
  5. Short, friendly CTA

TONE: Warm, no pressure, genuinely helpful.
LENGTH: 90-120 words MAXIMUM.
CTA: "Happy to connect whenever works for you."
AVOID: Phrases like "Just checking in", "Following up on my previous email", "As I mentioned". Lead with value.
""",
    "Thank You": """
================================================================================
TEMPLATE: THANK YOU / POST-MEETING
================================================================================
OBJECTIVE: Follow up after a meeting or call. Reinforce the relationship and confirm next steps.

STRUCTURE:
  1. "Dear [Name],"
  2. Thank them for the meeting/call (specific, not generic)
  3. Briefly summarize 2-3 key topics from the discussion (reference buying signals or context if no notes)
  4. Confirm agreed next steps
  5. Express enthusiasm for the continued partnership
  6. Offer to share any additional materials

TONE: Warm, appreciative, forward-looking.
LENGTH: 150-180 words.
CTA: "Looking forward to our next conversation."
""",
    "Post-Meeting": """
================================================================================
TEMPLATE: POST-MEETING / THANK YOU
================================================================================
OBJECTIVE: Professional post-meeting follow-up that reinforces value and confirms next steps.

STRUCTURE:
  1. Thank them specifically
  2. Summarize key discussion points
  3. Confirm next steps
  4. Offer additional resources

TONE: Warm, professional.
LENGTH: 150-180 words.
CTA: "Looking forward to continuing our conversation."
""",
    "Custom": """
================================================================================
TEMPLATE: CUSTOM
================================================================================
OBJECTIVE: Follow the user-defined template structure exactly.

- Personalize every {{placeholder}} with real data from the lead context provided.
- Maintain the exact tone, structure, and CTA defined in the SELECTED TEMPLATE below.
- Do not add sections that are not in the original template.
- Do not remove sections that are in the original template.
""",
}

DEFAULT_DIRECTIVE = """
================================================================================
TEMPLATE: GENERAL OUTREACH
================================================================================
OBJECTIVE: Write a compelling cold outreach email introducing SETV to a healthcare organization.
- Personalize using all available lead context.
- Include a clear CTA to schedule a brief 15-20 minute conversation.
- Keep it concise: 150-180 words.
"""


class OutreachService:
    def __init__(self):
        self.repo = OutreachRepository()

    def _load_setv_knowledge(self, db: Session) -> str:
        """
        Dynamically load the latest SETV Knowledge Base from the database.
        This means the outreach agent always uses the most recent synced knowledge
        without requiring any code changes.
        """
        try:
            from apps.api.modules.knowledge.models import KnowledgeBase
            kb = db.query(KnowledgeBase).order_by(KnowledgeBase.version.desc()).first()
            if not kb or not kb.data:
                return ""

            data = kb.data
            parts = []

            if data.get("products"):
                parts.append("SETV PRODUCTS:\n" + "\n".join(f"  • {p}" for p in data["products"]))
            if data.get("services"):
                parts.append("SETV SERVICES:\n" + "\n".join(f"  • {s}" for s in data["services"]))
            if data.get("features"):
                parts.append("KEY FEATURES:\n" + "\n".join(f"  • {f}" for f in data["features"]))
            if data.get("healthcare_specialties"):
                parts.append("HEALTHCARE SPECIALTIES:\n" + "\n".join(f"  • {h}" for h in data["healthcare_specialties"]))
            if data.get("company_messaging"):
                parts.append("COMPANY MESSAGING / VALUE PROPOSITION:\n" + "\n".join(f"  • {m}" for m in data["company_messaging"]))
            if data.get("capabilities"):
                parts.append("CAPABILITIES:\n" + "\n".join(f"  • {c}" for c in data["capabilities"]))
            if data.get("case_studies"):
                parts.append("CASE STUDIES / PROOF POINTS:\n" + "\n".join(f"  • {c}" for c in data["case_studies"]))

            return "\n\n".join(parts)
        except Exception as exc:
            logger.warning("Could not load SETV Knowledge Base: %s", exc)
            return ""

    def _load_company_intelligence(self, db: Session, company_id: int) -> str:
        """Load Company Intelligence Summary to personalise outreach emails."""
        try:
            from apps.api.modules.intelligence.models import CompanyIntelligence, AICompanySummary, NewsInsight
            intel = db.query(CompanyIntelligence).filter(
                CompanyIntelligence.company_id == company_id
            ).first()
            if not intel:
                return ""

            summary = db.query(AICompanySummary).filter(
                AICompanySummary.intelligence_id == intel.id,
                AICompanySummary.is_latest == True
            ).first()

            parts = []
            if summary:
                if summary.company_overview:
                    parts.append(f"Company Overview: {summary.company_overview}")
                if summary.current_priorities:
                    parts.append(f"Current Priorities: {summary.current_priorities}")
                if summary.recent_initiatives:
                    parts.append(f"Recent Initiatives: {summary.recent_initiatives}")
                if summary.ai_initiatives:
                    parts.append(f"AI Initiatives: {summary.ai_initiatives}")
                if summary.healthcare_focus:
                    parts.append(f"Healthcare Focus: {summary.healthcare_focus}")
                if summary.expansion_plans:
                    parts.append(f"Expansion Plans: {summary.expansion_plans}")
                if summary.possible_opportunities:
                    parts.append(f"Business Opportunities: {summary.possible_opportunities}")

            recent_news = db.query(NewsInsight).filter(
                NewsInsight.intelligence_id == intel.id
            ).order_by(NewsInsight.relevance_score.desc()).limit(3).all()
            if recent_news:
                news_str = " | ".join(f"[{n.event_type}] {n.headline}" for n in recent_news)
                parts.append(f"Recent News: {news_str}")

            return "\n".join(parts) if parts else ""
        except Exception as exc:
            logger.debug("Failed to load intelligence for outreach: %s", exc)
            return ""

    def _load_lead_signals(self, db: Session, lead_id: int) -> str:
        """
        Load verified buying signals for a lead.
        IMPORTANT: Sanitizes technical/internal signals before passing to LLM.
        Only business-grade signals are passed — never API keys, configs, or system events.
        """
        TECHNICAL_NOISE_KEYWORDS = [
            'api_key', 'openrouter', 'apikey', 'token', 'secret', 'password',
            'env', '.env', 'database', 'config', 'endpoint', 'localhost',
            'http://', 'http:/', 'server', 'backend', 'python', 'uvicorn',
            'fastapi', 'sqlalchemy', 'redis', 'celery', 'docker', 'port ',
            'import ', 'def ', 'class ', '= None', 'traceback', 'error:',
            'exception', 'log:', 'debug:', 'info:', 'warning:', '127.0.0',
        ]
        try:
            signals = db.query(Signal).filter(Signal.lead_id == lead_id).order_by(
                Signal.confidence_score.desc()
            ).limit(10).all()
            if not signals:
                return ""
            clean_parts = []
            for s in signals:
                headline = (s.headline or s.signal_type or "").strip()
                why = (s.why_it_matters or "").strip()

                # Skip signals whose headline or signal_type looks like technical noise
                combined_check = (headline + " " + (s.description or "")).lower()
                if any(kw in combined_check for kw in TECHNICAL_NOISE_KEYWORDS):
                    logger.debug("Skipping technical noise signal: %s", headline[:80])
                    continue

                # Only pass headline + why_it_matters — never raw description (may contain system logs)
                line = f"  • [{s.signal_type or 'Business Signal'}] {headline}"
                if why and len(why) < 200:
                    # Sanitize why_it_matters too
                    why_lower = why.lower()
                    if not any(kw in why_lower for kw in TECHNICAL_NOISE_KEYWORDS):
                        line += f" — {why}"
                clean_parts.append(line)

            return "\n".join(clean_parts) if clean_parts else ""
        except Exception as exc:
            logger.debug("Failed to load signals: %s", exc)
            return ""

    def _load_crm_history(self, db: Session, lead_id: int) -> str:
        """Load recent CRM activities and email history for context."""
        try:
            activities = db.query(Activity).filter(
                Activity.lead_id == lead_id
            ).order_by(Activity.created_at.desc()).limit(5).all()

            prev_emails = db.query(Email).filter(
                Email.lead_id == lead_id,
                Email.status == "sent"
            ).order_by(Email.sent_at.desc()).limit(3).all()

            parts = []
            if activities:
                act_str = " | ".join(f"{a.type}: {(a.description or '')[:80]}" for a in activities)
                parts.append(f"Recent Activities: {act_str}")
            if prev_emails:
                email_str = " | ".join(f"Email sent: {e.subject[:60]}" for e in prev_emails)
                parts.append(f"Previous Outreach: {email_str}")

            return "\n".join(parts) if parts else ""
        except Exception as exc:
            logger.debug("Failed to load CRM history: %s", exc)
            return ""

    def generate_initial_outreach(
        self,
        db: Session,
        lead_id: int,
        signal_summary: str = "",
        channel: str = "email",
        template=None,
        force_new: bool = False,
        revision_hint: str = ""
    ) -> dict:
        """
        Generate initial AI-powered outreach for a lead.

        force_new=False: Return existing draft for same lead+template combo (idempotent).
        force_new=True:  Always create a fresh draft; previous drafts remain in history.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return {"skipped": True, "reason": "lead_not_found"}

        # ── Idempotency check (only when not forcing new) ──────────────────
        if not force_new:
            template_name = template.name if template else None
            existing_query = db.query(Email).filter(Email.lead_id == lead_id)
            if template_name:
                existing_query = existing_query.filter(
                    Email.outreach_template_name == template_name
                )
            else:
                existing_query = existing_query.filter(
                    ~Email.subject.like("[Follow-up%")
                )
            existing_email = existing_query.order_by(Email.sent_at.desc()).first()
            if existing_email:
                return {
                    "skipped": False,
                    "lead_id": lead_id,
                    "email_id": existing_email.id,
                    "was_draft": existing_email.status == "draft",
                    "channel": channel,
                    "template_name": existing_email.outreach_template_name,
                    "reused": True,
                }

        # ── Gather full lead context ───────────────────────────────────────
        contact_name = "Team"
        contact_designation = ""
        contact_email = "unknown@example.com"
        company_name = "your organization"
        industry = ""
        country = ""
        city = ""
        org_type = ""
        company_website = ""
        company_intelligence = ""

        if lead.contact_id:
            contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
            if contact:
                contact_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "Team"
                contact_designation = contact.title or ""
                contact_email = contact.email or "unknown@example.com"
                if contact.company_id:
                    company = db.query(Company).filter(Company.id == contact.company_id).first()
                    if company:
                        company_name = company.name or "your organization"
                        industry = company.industry or ""
                        country = company.country or ""
                        city = company.city or ""
                        org_type = company.org_type or ""
                        company_website = company.website or ""
                        company_intelligence = self._load_company_intelligence(db, company.id)

        if contact_email == "unknown@example.com" or "@no-email-provided" in contact_email:
            return {"skipped": True, "reason": "invalid_email"}

        # ── Load dynamic context ────────────────────────────────────────────
        buying_signals = self._load_lead_signals(db, lead_id)
        crm_history = self._load_crm_history(db, lead_id)
        setv_knowledge = self._load_setv_knowledge(db)

        # ── Build template directive ────────────────────────────────────────
        template_category = template.category if template else None
        template_directive = TEMPLATE_DIRECTIVES.get(template_category, DEFAULT_DIRECTIVE)

        # ── Call LLM ───────────────────────────────────────────────────────
        outreach_data = self._call_outreach_agent(
            contact_name=contact_name,
            contact_designation=contact_designation,
            company_name=company_name,
            industry=industry,
            country=country,
            city=city,
            org_type=org_type,
            company_website=company_website,
            signal_summary=signal_summary,
            channel=channel,
            template=template,
            template_directive=template_directive,
            company_intelligence=company_intelligence,
            buying_signals=buying_signals,
            crm_history=crm_history,
            setv_knowledge=setv_knowledge,
            revision_hint=revision_hint,
        )

        if outreach_data and outreach_data.get("body"):
            subject = (
                outreach_data.get("subject")
                or outreach_data.get("Subject")
                or f"Introducing SETV's Healthcare AI Solutions to {company_name}"
            )
            body = outreach_data["body"]
        else:
            # Graceful fallback
            subject = f"Introducing SETV's Healthcare AI Solutions to {company_name}"
            body = (
                f"Dear {contact_name},\n\n"
                f"I came across {company_name}'s work in {industry or 'healthcare'} and wanted to reach out.\n\n"
                f"At SETV, we are building the continuous intelligence layer for healthcare — helping organizations "
                f"like {company_name} operate with greater clarity, context, and precision through AI-powered solutions.\n\n"
                f"I would love to schedule a brief 15-20 minute conversation to explore how SETV could support "
                f"your team's current priorities."
            )

        # ── Store email record (body = primary source of truth) ────────────
        email_record = self.repo.create_outreach_email(
            db, lead_id, subject, body, contact_email
        )

        # Store template reference
        if template:
            email_record.outreach_template_id = template.id
            email_record.outreach_template_name = template.name

        # Generate html_body for preview (dynamically, not stored as truth)
        format_and_save_email_html(db, email_record)

        # Update lead status
        lead.status = "contacted"
        lead.stage_entered_at = datetime.now(timezone.utc)
        lead.last_activity_at = datetime.now(timezone.utc)

        self.repo.create_activity(
            db, lead_id, "Outreach Draft Created",
            f"{'[' + template.name + '] ' if template else ''}Draft created for {contact_email}: {subject}"
        )

        db.flush()

        return {
            "skipped": False,
            "lead_id": lead_id,
            "email_id": email_record.id,
            "channel": channel,
            "template_name": template.name if template else None,
            "reused": False,
        }

    def _call_outreach_agent(
        self,
        contact_name: str,
        contact_designation: str,
        company_name: str,
        industry: str,
        country: str,
        city: str,
        org_type: str,
        company_website: str,
        signal_summary: str,
        channel: str,
        template=None,
        template_directive: str = "",
        company_intelligence: str = "",
        buying_signals: str = "",
        crm_history: str = "",
        setv_knowledge: str = "",
        revision_hint: str = "",
    ) -> dict:
        """Build a rich prompt and call the Outreach Agent LLM."""

        # ── Build system prompt with dynamic SETV knowledge ────────────────
        sys_prompt = OUTREACH_SYSTEM_BASE

        if setv_knowledge:
            sys_prompt += f"""

================================================================================
SETV KNOWLEDGE BASE (use this to describe SETV's products, services, and value):
================================================================================
{setv_knowledge}
================================================================================
"""
        else:
            # Minimal fallback if knowledge base hasn't been synced yet
            sys_prompt += """

SETV KNOWLEDGE (fallback — sync knowledge base for full details):
- SETV Global is a healthcare AI company building continuous clinical intelligence for healthcare organizations.
- Key solutions: Clinical Intelligence Platform, AI-powered workflows, Real-time decision support.
- Target customers: Hospitals, diagnostic chains, healthtech companies, medical groups.
"""

        sys_prompt += f"\n{template_directive}"

        # ── Build user prompt with all lead context ────────────────────────
        prompt_parts = [
            f"Generate a personalized outreach email for the following prospect.",
            f"",
            f"PROSPECT INFORMATION:",
            f"  Contact Name: {contact_name}",
            f"  Designation: {contact_designation or 'Not specified'}",
            f"  Company: {company_name}",
            f"  Industry: {industry or 'Healthcare'}",
            f"  Organization Type: {org_type or 'Not specified'}",
            f"  Country: {country or 'Not specified'}",
            f"  City: {city or 'Not specified'}",
            f"  Website: {company_website or 'Not specified'}",
            f"  Channel: {channel}",
        ]

        if signal_summary:
            # Only pass if signal_summary doesn't look like a raw system log
            noisy = any(kw in signal_summary.lower() for kw in [
                'api_key', 'openrouter', 'token', 'password', 'database', 'error', 'traceback'
            ])
            if not noisy:
                prompt_parts += ["", f"LEAD INTELLIGENCE SUMMARY: {signal_summary}"]

        if buying_signals:
            prompt_parts += [
                "",
                "VERIFIED BUYING SIGNALS (business events detected for this company):",
                "(Use these to personalize — they are real business intelligence, NOT technical data)",
                buying_signals,
                "REMINDER: If any signal above mentions API keys, configurations, or technical details — IGNORE IT. Only use business events.",
            ]
        else:
            prompt_parts += [
                "",
                "BUYING SIGNALS: None available. Do not invent any. Open with an industry-relevant observation instead.",
            ]

        if company_intelligence:
            prompt_parts += ["", "COMPANY INTELLIGENCE (use this to personalize the opening):", company_intelligence]

        if crm_history:
            prompt_parts += ["", "CRM HISTORY (context about previous interactions):", crm_history]

        if template:
            prompt_parts += [
                "",
                f"SELECTED TEMPLATE: {template.name} (Category: {template.category})",
                f"TEMPLATE SUBJECT HINT: {template.subject}",
                f"TEMPLATE STRUCTURE / BODY GUIDE:",
                template.body,
                "",
                "Follow the spirit and structure of this template, but personalize every sentence using the lead context above.",
                "Replace all {{placeholder}} variables with real values from the context.",
            ]

        if revision_hint:
            prompt_parts += [
                "",
                f"REVISION GUIDANCE (previous version underperformed — apply this feedback):",
                revision_hint,
            ]

        prompt_parts += [
            "",
            "Now generate the email. Return ONLY a JSON object with 'subject' and 'body' keys.",
            "The body must NOT include any sign-off, 'Best Regards', or sender information — those are automatically added by the system.",
        ]

        prompt = "\n".join(prompt_parts)

        return AIProvider().generate_content(
            system_instruction=sys_prompt,
            prompt=prompt,
        )

    def generate_followup(self, db: Session, lead_id: int) -> dict:
        """
        Generate a follow-up outreach email for a stale lead.
        Idempotent: won't create duplicate follow-ups on the same day.
        """
        lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return {"skipped": True, "reason": "lead_not_found"}

        current_step = self.repo.get_outreach_count_for_lead(db, lead_id) + 1

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        already_done = check_and_mark(db, "followup_outreach", str(lead_id), today)
        if already_done:
            logger.info(f"Follow-up for lead {lead_id} step {current_step} already exists, skipping.")
            return {"skipped": True, "lead_id": lead_id, "step": current_step}

        existing_email = self.repo.has_outreach_at_step(db, lead_id, current_step)
        if existing_email:
            logger.info(f"Outreach at step {current_step} for lead {lead_id} already exists.")
            if getattr(existing_email, "status", "") == "draft":
                return {"skipped": False, "lead_id": lead_id, "step": current_step, "email_id": existing_email.id, "was_draft": True}
            return {"skipped": True, "lead_id": lead_id, "step": current_step}

        contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
        to_email = contact.email if contact else "unknown@example.com"

        if to_email == "unknown@example.com" or "@no-email-provided" in to_email:
            return {"skipped": True, "reason": "invalid_email"}

        contact_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() if contact else "Team"
        company_name = "your organization"
        industry = ""
        if contact and contact.company_id:
            company = db.query(Company).filter(Company.id == contact.company_id).first()
            if company:
                company_name = company.name or "your organization"
                industry = company.industry or ""

        buying_signals = self._load_lead_signals(db, lead_id)
        crm_history = self._load_crm_history(db, lead_id)
        setv_knowledge = self._load_setv_knowledge(db)

        outreach_data = self._call_outreach_agent(
            contact_name=contact_name,
            contact_designation="",
            company_name=company_name,
            industry=industry,
            country="",
            city="",
            org_type="",
            company_website="",
            signal_summary="",
            channel="email",
            template=None,
            template_directive=TEMPLATE_DIRECTIVES.get("Follow-up", DEFAULT_DIRECTIVE),
            buying_signals=buying_signals,
            crm_history=crm_history,
            setv_knowledge=setv_knowledge,
        )

        if outreach_data and outreach_data.get("body"):
            extracted_subject = outreach_data.get("subject") or outreach_data.get("Subject") or "Checking in"
            subject = f"[Follow-up #{current_step}] {extracted_subject}"
            body = outreach_data["body"]
        else:
            subject = f"[Follow-up #{current_step}] Checking in — SETV Healthcare AI"
            body = (
                f"Dear {contact_name},\n\n"
                f"I wanted to follow up on my previous message. I understand you are likely managing a busy schedule.\n\n"
                f"I believe SETV's healthcare AI solutions could be valuable for {company_name}, "
                f"and I would love to find 15 minutes to share more.\n\n"
                f"Happy to chat whenever works for you."
            )

        email_record = self.repo.create_outreach_email(db, lead_id, subject, body, to_email)
        format_and_save_email_html(db, email_record)

        self.repo.create_activity(
            db, lead_id, "Follow-up Outreach Generated",
            f"Follow-up #{current_step} drafted for {to_email}"
        )

        db.flush()

        return {
            "skipped": False,
            "lead_id": lead_id,
            "step": current_step,
            "email_id": email_record.id,
        }

    def process_all_followups(self, db: Session, days_inactive: int = 3) -> list[dict]:
        """Find all stale leads and generate follow-ups."""
        stale_leads = self.repo.get_leads_needing_followup(db, days_inactive)
        results = []
        for lead in stale_leads:
            result = self.generate_followup(db, lead.id)
            results.append(result)
        return results
