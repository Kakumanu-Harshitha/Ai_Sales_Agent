"""
Meeting Scheduler Service — full CRM behavior.
Creates Google Calendar event, saves to PostgreSQL, updates Lead status, logs CRM activities.
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from fastapi import HTTPException
from googleapiclient.discovery import build

from apps.api.core.google_auth import get_google_credentials
from apps.api.modules.crm.models import Meeting, Activity, Lead, Contact

logger = logging.getLogger(__name__)


class MeetingsService:

    # ─── Google Calendar helper ───────────────────────────────────────────────
    def _get_calendar_service(self):
        creds = get_google_credentials()
        if not creds:
            raise HTTPException(status_code=401, detail="Google credentials not found or invalid")
        return build('calendar', 'v3', credentials=creds)

    def _get_gmail_profile(self):
        from googleapiclient.discovery import build as build_api
        creds = get_google_credentials()
        gmail = build_api('gmail', 'v1', credentials=creds)
        return gmail.users().getProfile(userId='me').execute()

    # ─── FREE SLOTS ───────────────────────────────────────────────────────────
    def get_free_slots(self, db: Session, account_id: int, start_date: datetime, end_date: datetime):
        service = self._get_calendar_service()
        body = {
            "timeMin": start_date.isoformat() + ('Z' if not start_date.tzinfo else ''),
            "timeMax": end_date.isoformat() + ('Z' if not end_date.tzinfo else ''),
            "items": [{"id": "primary"}]
        }
        result = service.freebusy().query(body=body).execute()
        return result['calendars']['primary']['busy']

    # ─── BOOK MEETING ─────────────────────────────────────────────────────────
    def book_meeting(
        self, db: Session, contact_id: int,
        contact_email: str, slot_start: datetime, slot_end: datetime,
        title: str, description: str, lead_id: int = None, timezone: str = None
    ) -> dict:

        logger.info("=" * 60)
        logger.info("STEP 1: Booking request received")
        logger.info(f"  Lead ID:        {lead_id}")
        logger.info(f"  Contact ID:     {contact_id}")
        logger.info(f"  Contact Email:  {contact_email}")
        logger.info(f"  Title:          {title}")
        logger.info(f"  Start:          {slot_start}")
        logger.info(f"  End:            {slot_end}")

        # ── Default end = start + 30 min if same ───────────────────────────
        if slot_end <= slot_start:
            slot_end = slot_start + timedelta(minutes=30)
            logger.info(f"  End adjusted to: {slot_end} (start + 30 min)")

        # ── Resolve lead ────────────────────────────────────────────────────
        lead = None
        if lead_id:
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
        if not lead and contact_id:
            lead = db.query(Lead).filter(Lead.contact_id == contact_id).first()

        lead_name = "Unknown"
        if lead:
            contact = db.query(Contact).filter(Contact.id == lead.contact_id).first()
            if contact:
                lead_name = f"{contact.first_name or ''} {contact.last_name or ''}".strip() or "Unknown"
                if not contact_email or contact_email == 'prospect@example.com':
                    contact_email = contact.email

        logger.info(f"  Lead Name:      {lead_name}")
        logger.info(f"  Resolved Email: {contact_email}")

        # ── Duplicate check ─────────────────────────────────────────────────
        if lead:
            existing = db.query(Meeting).filter(
                Meeting.lead_id == lead.id,
                Meeting.scheduled_at == slot_start
            ).first()
            if existing:
                logger.info("  Duplicate found — updating existing meeting instead")
                return self._update_existing(db, existing, slot_start, slot_end, title, description, contact_email, lead, lead_name)

        # ── Organizer email ─────────────────────────────────────────────────
        try:
            profile = self._get_gmail_profile()
            organizer_email = profile.get('emailAddress', '')
        except Exception:
            organizer_email = ''

        logger.info(f"  Organizer:      {organizer_email}")

        # ── STEP 2: Create Google Calendar event ────────────────────────────
        logger.info("STEP 2: Creating Google Calendar event...")
        service = self._get_calendar_service()

        # ── Timezone fix ─────────────────────────────────────────────────────
        # The frontend sends a naive datetime-local string (e.g. "2026-07-15T21:06").
        # Pydantic parses it as a naive datetime (tzinfo=None).
        # We must NOT append +00:00 or Z — that would tell Google it's UTC.
        # Instead, strip any tz suffix and pass timeZone: Asia/Kolkata (or user provided) so
        # Google Calendar interprets the wall-clock time as IST.
        CALENDAR_TIMEZONE = timezone or 'Asia/Kolkata'
        start_str = slot_start.strftime('%Y-%m-%dT%H:%M:%S')
        end_str   = slot_end.strftime('%Y-%m-%dT%H:%M:%S')

        logger.info(f"  Frontend selected time (naive):  {slot_start}  tzinfo={slot_start.tzinfo}")
        logger.info(f"  Final dateTime sent to Google:   {start_str}")
        logger.info(f"  Final end dateTime sent to Google: {end_str}")
        logger.info(f"  Google Calendar timezone:        {CALENDAR_TIMEZONE}")

        request_id = f"setv-{lead_id or contact_id}-{int(slot_start.timestamp())}"
        event_body = {
            'summary': title,
            'description': description or '',
            'start': {
                'dateTime': start_str,
                'timeZone': CALENDAR_TIMEZONE,
            },
            'end': {
                'dateTime': end_str,
                'timeZone': CALENDAR_TIMEZONE,
            },
            'attendees': [
                {'email': contact_email},
            ],
            'conferenceData': {
                'createRequest': {
                    'requestId': request_id,
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            },
            'sendUpdates': 'all',
        }

        try:
            created_event = service.events().insert(
                calendarId='primary',
                body=event_body,
                conferenceDataVersion=1,
                sendUpdates='all',
            ).execute()
        except Exception as e:
            logger.error(f"Google Calendar API error: {e}")
            raise HTTPException(status_code=500, detail=f"Google Calendar API error: {e}")

        google_event_id = created_event.get('id')
        google_event_link = created_event.get('htmlLink')
        logger.info(f"STEP 2 DONE: Google Calendar event created: {google_event_id}")

        # ── STEP 2b: Fetch event back to verify timezone ─────────────────────
        try:
            verified = service.events().get(calendarId='primary', eventId=google_event_id).execute()
            logger.info("STEP 2b VERIFY — Fetched event back from Google:")
            logger.info(f"  event.start.dateTime: {verified['start'].get('dateTime')}")
            logger.info(f"  event.start.timeZone: {verified['start'].get('timeZone')}")
            logger.info(f"  event.end.dateTime:   {verified['end'].get('dateTime')}")
            logger.info(f"  event.end.timeZone:   {verified['end'].get('timeZone')}")
            if verified['start'].get('timeZone') == 'Asia/Kolkata':
                logger.info("  [OK] TIMEZONE CORRECT — Google Calendar event is in IST (Asia/Kolkata)")
            else:
                logger.warning(f"  [X] TIMEZONE MISMATCH — expected Asia/Kolkata, got {verified['start'].get('timeZone')}")
        except Exception as ve:
            logger.warning(f"  Could not verify event timezone: {ve}")

        # ── STEP 3: Extract Meet link ────────────────────────────────────────
        meet_link = None
        conf_data = created_event.get('conferenceData', {})
        for entry in conf_data.get('entryPoints', []):
            if entry.get('entryPointType') == 'video':
                meet_link = entry.get('uri')
                break
        logger.info(f"STEP 3: Google Meet link: {meet_link}")
        logger.info("STEP 3: Invitation sent to attendee via sendUpdates='all'")

        # ── STEP 4: Save to PostgreSQL ────────────────────────────────────────
        logger.info("STEP 4: Inserting Meeting into PostgreSQL...")
        try:
            meeting = Meeting(
                lead_id=lead.id if lead else None,
                lead_name=lead_name,
                title=title,
                description=description,
                scheduled_at=slot_start,
                end_time=slot_end,
                timezone=CALENDAR_TIMEZONE,
                google_event_id=google_event_id,
                meet_link=meet_link,
                organizer_email=organizer_email,
                attendee_email=contact_email,
                calendar_status='confirmed',
                status='scheduled',
            )
            db.add(meeting)
            db.flush()
            logger.info(f"STEP 4 DONE: Meeting inserted — DB ID: {meeting.id}")
        except Exception as db_error:
            logger.error(f"DB insert failed: {db_error}")
            # Rollback and attempt to delete the Calendar event for consistency
            db.rollback()
            try:
                service.events().delete(calendarId='primary', eventId=google_event_id).execute()
                logger.warning(f"Google Calendar event {google_event_id} deleted (rollback)")
            except Exception:
                pass
            raise HTTPException(status_code=500, detail=f"Meeting saved to Google Calendar but DB insert failed: {db_error}")

        # ── STEP 5: Update Lead status ────────────────────────────────────────
        if lead:
            lead.status = 'meeting_booked'
            from datetime import timezone as dt_tz
            lead.last_activity_at = datetime.now(dt_tz.utc)
            logger.info(f"STEP 5: Lead {lead.id} status → meeting_booked")

        # ── STEP 6: CRM Activities ────────────────────────────────────────────
        if lead:
            for activity_type, desc in [
                ("Meeting Scheduled",          f"Meeting '{title}' scheduled for {slot_start.strftime('%Y-%m-%d %H:%M')} UTC with {contact_email}"),
                ("Google Calendar Event Created", f"Google Event ID: {google_event_id} | Link: {google_event_link or 'N/A'}"),
                ("Invitation Sent",             f"Google Calendar invitation sent to {contact_email} with Meet link: {meet_link}"),
            ]:
                activity = Activity(
                    lead_id=lead.id,
                    type=activity_type,
                    description=desc,
                )
                db.add(activity)
            logger.info("STEP 6: CRM activities logged")

        db.flush()
        logger.info("STEP 7: DB commit successful")
        logger.info("STEP 8: Sending frontend response")
        logger.info("=" * 60)

        return {
            "status": "success",
            "meeting_id": meeting.id,
            "meeting_link": meet_link,
            "event_id": google_event_id,
            "lead_id": lead.id if lead else None,
            "lead_name": lead_name,
            "attendee_email": contact_email,
            "organizer_email": organizer_email,
            "scheduled_at": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
        }

    def _update_existing(self, db, existing, slot_start, slot_end, title, description, contact_email, lead, lead_name):
        """Update an existing duplicate meeting record."""
        existing.title = title
        existing.description = description
        existing.end_time = slot_end
        existing.attendee_email = contact_email
        existing.status = 'rescheduled'
        db.flush()
        logger.info(f"Existing meeting {existing.id} updated (rescheduled)")
        return {
            "status": "updated",
            "meeting_id": existing.id,
            "meeting_link": existing.meet_link,
            "event_id": existing.google_event_id,
            "lead_id": lead.id if lead else None,
            "lead_name": lead_name,
            "attendee_email": contact_email,
            "scheduled_at": slot_start.isoformat(),
            "end_time": slot_end.isoformat(),
        }
