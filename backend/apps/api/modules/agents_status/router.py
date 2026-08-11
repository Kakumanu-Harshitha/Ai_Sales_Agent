from fastapi import APIRouter
from apps.api.core.scheduler import _scheduler
from datetime import datetime, timezone

router = APIRouter(prefix='/agents', tags=['Agents'])

_agent_log = {
    'prospecting': {'status': 'idle', 'last_run': None, 'last_result': None},
    'signal_detection': {'status': 'idle', 'last_run': None, 'last_result': None},
    'outreach': {'status': 'idle', 'last_run': None, 'last_result': None},
    'reply_handler': {'status': 'idle', 'last_run': None, 'last_result': None},
    'meeting_scheduler': {'status': 'idle', 'last_run': None, 'last_result': None},
    'crm': {'status': 'active', 'last_run': None, 'last_result': 'Always listening'},
    'pipeline': {'status': 'idle', 'last_run': None, 'last_result': None},
}


def update_agent_status(agent_name: str, status: str, result: str = None):
    """Update the in-memory agent status log. Call this from job functions."""
    if agent_name in _agent_log:
        _agent_log[agent_name]['status'] = status
        _agent_log[agent_name]['last_run'] = datetime.now(timezone.utc).isoformat()
        if result:
            _agent_log[agent_name]['last_result'] = result


@router.get('/status')
def get_agent_status():
    agents = []
    for name, info in _agent_log.items():
        jobs = []
        if _scheduler:
            jobs = [j for j in _scheduler.get_jobs() if name.replace('_', '') in j.id.replace('_', '')]
        next_run = None
        if jobs:
            next_run = str(jobs[0].next_run_time) if jobs[0].next_run_time else None
        agents.append({
            'name': name.replace('_', ' ').title(),
            'key': name,
            'status': info['status'],
            'last_run': info['last_run'],
            'next_run': next_run,
            'last_result': info['last_result'],
        })
    return {'agents': agents}
