import sys
import os
from datetime import datetime, timezone, timedelta

# Add the root directory to sys.path so we can import from apps
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))

from sqlalchemy.orm import Session
from apps.api.db.database import SessionLocal, engine
from apps.api.modules.crm.models import (
    Company, Contact, Lead, Signal, Meeting, Email, Reply, ReplyAnalysis, Activity
)

def utcnow():
    return datetime.now(timezone.utc)

def restore_data():
    db = SessionLocal()
    try:
        print("Restoring Companies...")
        companies_data = [
            (38, 'Apollo Hospitals', 'apollohospitals.com'),
            (17, '3853 ROSECRANS ST', 'apibhs.com'),
            (44, '1003 WALNUT ST INC', 'advsurgok.com'),
            (6, 'Healthcare Technologies Industry', 'pureglobal.com'),
            (64, 'HealthWorld Hospitals', 'healthworldhospitals.com'),
            (65, 'Karkinos Healthcare', 'karkinos.in'),
            (66, 'Paras Health', 'parashospitals.com'),
            (67, 'Bridge Health', 'bridgehealthgroup.com'),
            (68, 'TempHospital', 'temphospital.com'),
        ]
        for cid, name, domain in companies_data:
            c = db.query(Company).filter_by(id=cid).first()
            if not c:
                db.add(Company(id=cid, name=name, domain=domain, created_at=utcnow(), updated_at=utcnow()))

        print("Restoring Contacts...")
        contacts_data = [
            (38, 38, 'Harshitha', 'Kakumanu', 'kakumanuharshitha2006@gmail.com'),
            (17, 17, 'BAsada', '', 'BAsada@apibhs.com'),
            (44, 44, 'J', 'Veldstra', 'jveldstra@advsurgok.com'),
            (6, 6, 'Info', '', 'info@pureglobal.com'),
            (64, 64, 'Ajay', 'D', 'drajay@healthworldhospitals.com'),
            (65, 65, 'Vinod', 'Scaria', 'vinod.scaria@karkinos.in'),
            (66, 66, 'D', 'Nagar', 'drdnagar@parashospitals.com'),
            (67, 67, 'Karan', '', 'karan@bridgehealthgroup.com'),
            (68, 68, 'Aarav', 'Nrng', 'aaravnrng@gmail.com'),
        ]
        for cid, comp_id, fn, ln, email in contacts_data:
            c = db.query(Contact).filter_by(id=cid).first()
            if not c:
                db.add(Contact(id=cid, company_id=comp_id, first_name=fn, last_name=ln, email=email, created_at=utcnow(), updated_at=utcnow()))

        print("Restoring Leads...")
        leads_data = [
            (38, 38, 'meeting_booked', 'Prospecting Agent'),
            (17, 17, 'scored', 'Prospecting Agent'),
            (44, 44, 'scored', 'Prospecting Agent'),
            (6, 6, 'new', 'Prospecting Agent'),
            (64, 64, 'new', 'Prospecting Agent'),
            (65, 65, 'new', 'Prospecting Agent'),
            (66, 66, 'new', 'Prospecting Agent'),
            (67, 67, 'new', 'Prospecting Agent'),
            (68, 68, 'new', 'Prospecting Agent'),
            (31, 17, 'new', 'Prospecting Agent'),
        ]
        for lid, cont_id, status, source in leads_data:
            l = db.query(Lead).filter_by(id=lid).first()
            if not l:
                db.add(Lead(id=lid, contact_id=cont_id, status=status, source=source, stage_entered_at=utcnow(), last_activity_at=utcnow(), created_at=utcnow(), updated_at=utcnow()))
        
        db.commit() # Commit parents before inserting children

        print("Restoring specifics for Lead #38 (Harshitha / Apollo Hospitals)...")
        signals_38 = [
            (38, 'High Intent', 'Expressed interest in SETV CRM capabilities.', 8),
            (38, 'Website Visit', 'Visited pricing page multiple times.', 6),
            (38, 'Email Open', 'Opened outreach email within 5 minutes.', 4),
            (38, 'Link Click', 'Clicked case study link in email.', 5),
            (38, 'Decision Maker', 'Title identified as high-level decision maker.', 7),
            (38, 'Budget Indication', 'Mentioned software budget in previous reply.', 9),
            (38, 'Competitor Research', 'Asking about differences between SETV and Salesforce.', 8),
        ]
        for lid, s_type, desc, strength in signals_38:
            db.add(Signal(lead_id=lid, signal_type=s_type, description=desc, confidence_score=strength, created_at=utcnow(), updated_at=utcnow()))

        db.add(Meeting(lead_id=38, title='SETV Discovery Call', scheduled_at=utcnow() + timedelta(days=3), status='scheduled', created_at=utcnow(), updated_at=utcnow()))

        emails_38 = [
            (38, 'Introducing SETV CRM', 'Hi Harshitha, I wanted to introduce you to SETV...', 'sent', 'you@yourdomain.com', 'kakumanuharshitha2006@gmail.com'),
            (38, 'Re: Introducing SETV CRM', 'Just following up on my previous email.', 'sent', 'you@yourdomain.com', 'kakumanuharshitha2006@gmail.com'),
            (38, 'Case Study: Hospital CRM Success', 'Here is how we helped a similar hospital...', 'sent', 'you@yourdomain.com', 'kakumanuharshitha2006@gmail.com'),
        ]
        for lid, subj, body, stat, from_e, to_e in emails_38:
            db.add(Email(lead_id=lid, subject=subj, body=body, status=stat, from_email=from_e, to_email=to_e, sent_at=utcnow()))

        replies_38 = [
            (38, 'msg_001', 'Yes, I am interested. Let us schedule a call.', 'Meeting Request', 'Positive'),
            (38, 'msg_002', 'Wednesday works for me.', 'Confirmation', 'Neutral'),
        ]
        for lid, msg_id, content, intent, sentiment in replies_38:
            reply = Reply(lead_id=lid, message_id=msg_id, content=content, raw_body=content, clean_body=content, received_at=utcnow(), created_at=utcnow(), processed=True)
            db.add(reply)
            db.flush()
            db.add(ReplyAnalysis(reply_id=reply.id, intent=intent, sentiment=sentiment, analyzed_at=utcnow()))

        activities_38 = [
            (38, 'Lead Created', 'Discovered via Prospecting Agent: Apollo Hospitals', 5),
            (38, 'Email Sent', 'Sent "Introducing SETV CRM"', 4),
            (38, 'Signal Detected', 'Signal: Website Visit', 3),
            (38, 'Reply Received', 'Received reply: Yes, I am interested...', 2),
            (38, 'Meeting Scheduled', 'Scheduled: SETV Discovery Call', 1),
        ]
        for lid, a_type, desc, days_ago in activities_38:
            db.add(Activity(lead_id=lid, type=a_type, description=desc, created_at=utcnow() - timedelta(days=days_ago)))

        print("Restoring specifics for Lead #17...")
        signals_17 = [
            (17, 'Recent Funding', 'Company recently raised Series B funding.', 8),
            (17, 'Hiring Spree', 'Actively hiring for Sales Operations roles.', 7),
            (17, 'Tech Stack', 'Currently using legacy CRM system ripe for replacement.', 9),
        ]
        for lid, s_type, desc, strength in signals_17:
            db.add(Signal(lead_id=lid, signal_type=s_type, description=desc, confidence_score=strength, created_at=utcnow(), updated_at=utcnow()))
        
        db.add(Activity(lead_id=17, type='Lead Created', description='Discovered via Prospecting Agent: 3853 ROSECRANS ST', created_at=utcnow()))
        db.add(Activity(lead_id=17, type='Signal Detected', description='Detected 3 buying signals during enrichment', created_at=utcnow()))

        print("Restoring specifics for Lead #44...")
        db.add(Signal(lead_id=44, signal_type='Job Change', description='Contact recently promoted to Director level.', confidence_score=6, created_at=utcnow(), updated_at=utcnow()))
        db.add(Activity(lead_id=44, type='Lead Created', description='Discovered via Prospecting Agent: 1003 WALNUT ST INC', created_at=utcnow()))
        db.add(Activity(lead_id=44, type='Signal Detected', description='Detected 1 buying signal during enrichment', created_at=utcnow()))

        db.commit()
        print("Data insertion successful!")

        # Fix sequence counters
        print("Fixing sequences...")
        if engine.dialect.name == "postgresql":
            from sqlalchemy import text
            db.execute(text("SELECT setval('companies_id_seq', COALESCE((SELECT MAX(id) FROM companies), 1))"))
            db.execute(text("SELECT setval('contacts_id_seq', COALESCE((SELECT MAX(id) FROM contacts), 1))"))
            db.execute(text("SELECT setval('leads_id_seq', COALESCE((SELECT MAX(id) FROM leads), 1))"))
            db.commit()
            print("PostgreSQL sequences fixed.")

    except Exception as e:
        db.rollback()
        print(f"Error restoring data: {e}")
        raise
    finally:
        db.close()

if __name__ == '__main__':
    restore_data()
