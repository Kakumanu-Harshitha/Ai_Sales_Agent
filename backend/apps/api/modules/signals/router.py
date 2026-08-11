from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from apps.api.db.database import get_db
from .service import SignalsService
from apps.api.modules.crm.models import Signal, Lead, LeadScore

router = APIRouter(prefix='/signals', tags=['Signals'])
service = SignalsService()


@router.post('/scan/{lead_id}')
def scan_lead(lead_id: int, db: Session = Depends(get_db)):
    result = service.scan_lead_signals(db, lead_id)
    db.commit()
    return result


@router.post('/scan-all')
def scan_all_leads(db: Session = Depends(get_db)):
    results = service.scan_all_eligible_leads(db)
    db.commit()
    return {'results': results, 'total': len(results)}


@router.get('/list/{lead_id}')
def list_signals(lead_id: int, db: Session = Depends(get_db)):
    signals = db.query(Signal).filter(Signal.lead_id == lead_id).order_by(Signal.created_at.desc()).all()
    score_row = db.query(LeadScore).filter(LeadScore.lead_id == lead_id).order_by(LeadScore.created_at.desc()).first()
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    return {
        'lead_id': lead_id,
        'signals': [
            {
                'id': s.id,
                'signal_type': s.signal_type,
                'description': s.description,
                'created_at': str(s.created_at),
            }
            for s in signals
        ],
        'lead_score': score_row.score if score_row else (lead.lead_score if lead else None),
        'priority': lead.priority if lead else None,
    }
