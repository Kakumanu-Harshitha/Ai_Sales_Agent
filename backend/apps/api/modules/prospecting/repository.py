"""
Prospecting module — stores user-selected leads into CRM PostgreSQL.

Fixed bugs:
- Bug 5: Contact.email has nullable=False + unique=True on the DB column.
  When Gemini returns a contact without an email, inserting email=None causes
  an IntegrityError that rolls back the entire lead transaction.
  Fix: skip storing contacts that have no email (they are added to company
  record context only). A placeholder synthetic email is NOT used because the
  SOP forbids fabrication.
"""

import logging
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from apps.api.modules.crm.models import Company, Contact, Lead, Activity

logger = logging.getLogger(__name__)


class ProspectingRepository:

    def store_discovered_lead(self, db: Session, lead_data: dict) -> Lead:
        """
        Store a discovered lead into CRM tables:
        Company → Contact(s) → Lead → Activity

        GATE: A lead is only pushed to CRM if at least one contact has a
        verified email OR a phone number. Leads without any contact info
        are skipped (not pushed) to keep the CRM clean.

        Contacts without a verified email are NOT stored (email is required
        by the Contact table schema and must not be fabricated).
        """
        # 1. Upsert Company ────────────────────────────────────────────────
        website = lead_data.get("website") or ""
        domain = None
        if website:
            from urllib.parse import urlparse
            url = website if website.startswith("http") else f"https://{website}"
            parsed = urlparse(url)
            domain = parsed.hostname  # e.g. "apollohospitals.com"

        company = None
        if domain:
            company = db.query(Company).filter(Company.domain == domain).first()
        if not company:
            company_name = lead_data.get("company_name", "")
            if company_name:
                company = db.query(Company).filter(Company.name == company_name).first()

        if not company:
            company = Company(
                name=lead_data.get("company_name") or website or "Unknown",
                domain=domain,
                industry=lead_data.get("industry") or lead_data.get("org_type"),
                website=website or None,
                org_type=lead_data.get("org_type") or lead_data.get("industry"),
                state=lead_data.get("state"),
                city=lead_data.get("city"),
                country=lead_data.get("country", "India"),
            )
            db.add(company)
            db.flush()

        # 2. Check contacts for usable contact info (email OR phone) ────────
        contacts_data = lead_data.get("contacts", [])

        has_contact_info = any(
            (c.get("public_business_email") or "").strip()
            or (c.get("public_phone_number") or "").strip()
            for c in contacts_data
        )

        if not has_contact_info:
            company_name = lead_data.get("company_name", "Unknown")
            logger.info(
                "SKIP lead for '%s' — no contact has email or phone. "
                "Not pushing to CRM.",
                company_name,
            )
            raise ValueError(
                f"No contact info (email/phone) for '{company_name}' — lead not pushed to CRM."
            )

        # 3. Upsert Contacts (only those with a verified email) ─────────────
        first_contact = None

        for c in contacts_data:
            email = (c.get("public_business_email") or "").strip() or None
            phone = (c.get("public_phone_number") or "").strip() or None

            if not email:
                # Contact has phone but no email — log and skip DB insert
                # (Contact.email is NOT NULL in schema; we cannot fabricate one)
                if phone:
                    logger.info(
                        "Contact '%s' has phone %s but no email — skipping Contact row.",
                        c.get("name"), phone,
                    )
                continue

            # Check for existing contact by email
            existing = db.query(Contact).filter(Contact.email == email).first()
            if existing:
                if not first_contact:
                    first_contact = existing
                continue

            name = c.get("name") or ""
            parts = name.split(" ", 1)
            first_name = parts[0] if parts else None
            last_name = parts[1] if len(parts) > 1 else None

            contact = Contact(
                company_id=company.id,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                title=c.get("designation") or None,
                linkedin_url=c.get("linkedin_profile") or None,
            )
            db.add(contact)
            db.flush()
            if not first_contact:
                first_contact = contact

        if not first_contact:
            company_name = company.name if company else "Unknown"
            logger.info(
                "SKIP lead for '%s' — no valid contact with an email could be created.",
                company_name,
            )
            raise ValueError(
                f"No valid contact (requires email) for '{company_name}' — lead not pushed."
            )

        # 4. Create Lead ───────────────────────────────────────────────────
        lead = Lead(
            contact_id=first_contact.id,
            status="new",
            source=lead_data.get("source_type") or "Prospecting Agent",
            stage_entered_at=datetime.utcnow(),
            last_activity_at=datetime.utcnow(),
        )
        db.add(lead)
        db.flush()

        # 5. Immutable CRM Activity ────────────────────────────────────────
        activity = Activity(
            lead_id=lead.id,
            type="Lead Created",
            description=(
                f"Discovered via Prospecting Agent: "
                f"{lead_data.get('company_name', 'Unknown')} "
                f"| {lead_data.get('industry', 'Healthcare')} "
                f"| {lead_data.get('location', '')}"
            ),
        )
        db.add(activity)
        db.flush()

        return lead

