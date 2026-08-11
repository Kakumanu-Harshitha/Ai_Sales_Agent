import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';


export default function MeetingsPage() {
  const [meetings, setMeetings] = useState<Meeting[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);
  const [form, setForm] = useState({ 
    lead_id: '', 
    title: '', 
    scheduled_at: '', 
    description: '',
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  });
  const [bookResult, setBookResult] = useState<any>(null);
  const [bookError, setBookError] = useState<string | null>(null);
  const [leads, setLeads] = useState<Lead[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    const d = await fetchJSON<{ meetings: Meeting[]; total: number }>('/calendar/meetings?limit=200');
    if (d) { setMeetings(d.meetings); setTotal(d.total); }
    const ld = await fetchJSON<{ leads: Lead[] }>('/leads?limit=200');
    if (ld) setLeads(ld.leads);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const bookMeeting = async () => {
    if (!form.lead_id || !form.scheduled_at) return;
    setBooking(true);
    setBookError(null);
    setBookResult(null);
    const lead = leads.find(l => l.id === parseInt(form.lead_id));
    const res = await postJSON<any>('/calendar/book', {
      account_id: 1,
      contact_id: lead?.contact_id || 1,
      lead_id: lead?.id,
      // contact_email intentionally omitted — backend resolves from DB
      slot_start: form.scheduled_at,
      // slot_end omitted — backend defaults to start + 30 min
      title: form.title || 'SETV Discovery Call',
      description: form.description || 'AI-scheduled discovery meeting via SETV Sales Agent',
      timezone: form.timezone,
    });
    setBooking(false);
    if (res?.status === 'success' || res?.status === 'updated') {
      setBookResult(res);
      await load(); // auto-reload meetings list
    } else {
      setBookError(JSON.stringify(res));
    }
  };

  return (
    <>
      <div className="page-header">
        <div><div className="page-title">📅 Meeting Scheduler</div><div className="page-subtitle">Google Calendar integration — {total} meetings total</div></div>
        <button className="btn btn-primary" onClick={load}>↻ Refresh</button>
      </div>

      <div className="grid-2" style={{ alignItems: 'start' }}>
        <div className="card">
          <div className="card-title" style={{ marginBottom: 16 }}>Book New Meeting</div>
          <div className="form-group" style={{ marginBottom: 16 }}>
            <label className="form-label">Lead</label>
            <select value={form.lead_id} onChange={e => setForm(f => ({ ...f, lead_id: e.target.value }))}>
              <option value="">Select lead...</option>
              {leads.map(l => <option key={l.id} value={l.id}>{getLeadDisplayName(l)} ({l.status})</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 16 }}>
            <label className="form-label">Meeting Title</label>
            <input placeholder="SETV Discovery Call" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} />
          </div>
          <div className="form-group" style={{ marginBottom: 16 }}>
            <label className="form-label">Timezone</label>
            <select value={form.timezone} onChange={e => setForm(f => ({ ...f, timezone: e.target.value }))}>
              {['UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 
                'Europe/London', 'Europe/Paris', 'Asia/Kolkata', 'Asia/Tokyo', 'Australia/Sydney', 
                Intl.DateTimeFormat().resolvedOptions().timeZone].filter((v, i, a) => a.indexOf(v) === i).map(tz => (
                <option key={tz} value={tz}>{tz}</option>
              ))}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 16 }}>
            <label className="form-label">Date &amp; Time (in selected timezone, 30-min session)</label>
            <input type="datetime-local" value={form.scheduled_at} onChange={e => setForm(f => ({ ...f, scheduled_at: e.target.value }))} />
          </div>
          <div className="form-group" style={{ marginBottom: 20 }}>
            <label className="form-label">Agenda / Description</label>
            <textarea placeholder="Meeting agenda..." value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))} />
          </div>
          <button className="btn btn-primary" onClick={bookMeeting} disabled={booking || !form.lead_id || !form.scheduled_at}>
            {booking ? <><div className="spinner" style={{ width: 16, height: 16, margin: 0 }} />Booking...</> : '📅 Book via Google Calendar'}
          </button>
          {bookResult && (
            <div style={{ marginTop: 16, padding: '14px 16px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 8, fontSize: 13, lineHeight: 1.8 }}>
              <div style={{ color: 'var(--green)', fontWeight: 700, marginBottom: 6 }}>✓ Meeting Booked!</div>
              <div><b>Meeting ID:</b> #{bookResult.meeting_id}</div>
              <div><b>Attendee:</b> {bookResult.attendee_email}</div>
              <div><b>Organizer:</b> {bookResult.organizer_email}</div>
              <div><b>Scheduled:</b> {bookResult.scheduled_at ? new Date(bookResult.scheduled_at).toLocaleString() : '—'}</div>
              {bookResult.meeting_link && <div style={{ marginTop: 8 }}><a href={bookResult.meeting_link} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-glow)' }}>🎥 Join Google Meet ↗</a></div>}
            </div>
          )}
          {bookError && (
            <div style={{ marginTop: 16, padding: '12px 16px', background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.2)', borderRadius: 8, fontSize: 13, color: 'var(--red)' }}>
              ✗ {bookError}
            </div>
          )}
        </div>

        <div className="card">
          <div className="card-title" style={{ marginBottom: 16 }}>All Meetings</div>
          {loading ? <Spinner /> : meetings.length === 0 ? (
            <div className="empty-state">No meetings yet. Book one using the form.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Lead</th><th>Title</th><th>Attendee</th><th>Scheduled</th><th>Status</th><th>Meet</th></tr></thead>
                <tbody>
                  {meetings.map(m => (
                    <tr key={m.id}>
                      <td style={{ color: 'var(--text-muted)' }}>#{m.id}</td>
                      <td>{(m as any).lead_name || `Lead #${m.lead_id || '—'}`}</td>
                      <td style={{ fontWeight: 500 }}>{m.title || 'Discovery Call'}</td>
                      <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{(m as any).attendee_email || '—'}</td>
                      <td style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
                        {fmtDate(m.scheduled_at)}
                        {m.timezone && <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{m.timezone}</div>}
                      </td>
                      <td><StatusBadge status={m.status} /></td>
                      <td>{m.meet_link ? <a href={m.meet_link} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-glow)', fontSize: 13 }}>Join ↗</a> : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  );
}



