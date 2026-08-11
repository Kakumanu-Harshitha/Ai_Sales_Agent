import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';

function StatusChanger({ leadId, currentStatus, onChange }: { leadId: number, currentStatus: string, onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [val, setVal] = useState(currentStatus);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    if (val === currentStatus) return setEditing(false);
    setSaving(true);
    await postJSON(`/crm/leads/${leadId}/status`, { status: val });
    setSaving(false);
    setEditing(false);
    onChange();
  };

  if (!editing) return <div style={{ fontSize: 13, color: 'var(--accent-glow)', cursor: 'pointer', marginTop: 4, textAlign: 'right' }} onClick={() => setEditing(true)}>Change Status ✏️</div>;

  return (
    <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
      <select className="input" value={val} onChange={e => setVal(e.target.value)} disabled={saving} style={{ padding: '2px 6px', fontSize: 12, height: 24 }}>
        {['discovered', 'scored', 'outreach_pending', 'contacted', 'replied', 'meeting_booked', 'proposal_sent', 'won', 'lost'].map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      <button className="btn btn-primary" style={{ padding: '2px 8px', fontSize: 12, height: 24 }} onClick={save} disabled={saving}>Save</button>
      <button className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: 12, height: 24 }} onClick={() => setEditing(false)} disabled={saving}>Cancel</button>
    </div>
  );
}

function CompanyIntelligenceTab({ companyId }: { companyId: number }) {
  const [intel, setIntel] = useState<CompanyIntelligenceOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const loadIntel = useCallback(async () => {
    setLoading(true);
    const d = await fetchJSON<CompanyIntelligenceOut>(`/intelligence/company/${companyId}`);
    if (d) setIntel(d);
    setLoading(false);
  }, [companyId]);

  useEffect(() => { loadIntel(); }, [loadIntel]);

  const triggerRefresh = async () => {
    setRefreshing(true);
    await postJSON(`/intelligence/company/${companyId}/refresh`);
    setTimeout(loadIntel, 2000); // Give it a couple seconds
    setRefreshing(false);
  };

  if (loading) return <Spinner />;
  if (!intel) return (
    <div className="empty-state">
      <div style={{ marginBottom: 16 }}>No intelligence profile exists for this company yet.</div>
      <button className="btn btn-primary" onClick={triggerRefresh} disabled={refreshing}>
        {refreshing ? 'Triggering...' : 'Generate Intelligence Now'}
      </button>
    </div>
  );

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <span style={{ fontSize: 12, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>Last Refreshed</span>
          <div style={{ fontSize: 14 }}>{fmtDate(intel.last_refreshed_at) || 'Pending'}</div>
        </div>
        <button className="btn btn-ghost" onClick={triggerRefresh} disabled={refreshing}>
          {refreshing ? 'Refreshing...' : '↻ Force Refresh'}
        </button>
      </div>

      {intel.ai_summary ? (
        <div className="card" style={{ background: 'rgba(99,102,241,0.05)', borderColor: 'rgba(99,102,241,0.2)' }}>
          <div className="card-title" style={{ color: 'var(--accent-glow)' }}>AI Executive Summary</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {intel.ai_summary.company_overview && <div><strong>Overview:</strong> <span style={{ color: 'var(--text-secondary)' }}>{intel.ai_summary.company_overview}</span></div>}
            {intel.ai_summary.current_priorities && <div><strong>Current Priorities:</strong> <span style={{ color: 'var(--text-secondary)' }}>{intel.ai_summary.current_priorities}</span></div>}
            {intel.ai_summary.recent_initiatives && <div><strong>Recent Initiatives:</strong> <span style={{ color: 'var(--text-secondary)' }}>{intel.ai_summary.recent_initiatives}</span></div>}
            {intel.ai_summary.buying_signals_detected && <div><strong>Pre-Detected Signals:</strong> <span style={{ color: 'var(--text-secondary)' }}>{intel.ai_summary.buying_signals_detected}</span></div>}
            {intel.ai_summary.possible_opportunities && <div><strong>Possible Opportunities:</strong> <span style={{ color: 'var(--amber)' }}>{intel.ai_summary.possible_opportunities}</span></div>}
          </div>
        </div>
      ) : (
        <div className="alert-item alert-stalled" style={{ marginBottom: 0 }}>AI Summary generation is pending...</div>
      )}

      {intel.news_insights.length > 0 && (
        <div>
          <div className="card-title">Recent News & Press ({intel.news_insights.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {intel.news_insights.slice(0, 5).map((n, i) => (
              <div key={i} style={{ padding: 12, background: 'var(--bg-card-hover)', borderRadius: 8 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}><a href={n.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-glow)', textDecoration: 'none' }}>{n.headline}</a></div>
                {n.event_type && <span className="badge badge-blue" style={{ marginBottom: 8 }}>{n.event_type}</span>}
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{n.source_name} • {fmtDate(n.published_date)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {intel.linkedin_insights.length > 0 && (
        <div>
          <div className="card-title">LinkedIn Intelligence ({intel.linkedin_insights.length})</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {intel.linkedin_insights.slice(0, 5).map((l, i) => (
              <div key={i} style={{ padding: 12, background: 'var(--bg-card-hover)', borderRadius: 8 }}>
                {l.post_type && <span className="badge badge-purple" style={{ marginBottom: 8 }}>{l.post_type}</span>}
                <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 8 }}>{l.headline}</div>
                <div style={{ display: 'flex', gap: 6 }}>
                  {l.is_hiring && <span className="badge badge-green">Hiring</span>}
                  {l.is_expansion && <span className="badge badge-amber">Expansion</span>}
                  {l.is_ai_initiative && <span className="badge badge-cyan">AI Initiative</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      
      {intel.website_insights.length > 0 && (
        <div>
          <div className="card-title">Website Scrape Status</div>
          <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            Successfully extracted data from {intel.website_insights.length} key pages.
          </div>
        </div>
      )}
    </div>
  );
}

export default function CRMPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [selectedLeadId, setSelectedLeadId] = useState<number | null>(null);
  const [detail, setDetail] = useState<LeadFullDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailTab, setDetailTab] = useState<'timeline' | 'emails' | 'signals' | 'calls' | 'intelligence'>('timeline');
  const [callForm, setCallForm] = useState({ outcome: 'connected', duration_minutes: '', notes: '', follow_up_required: false });
  const [addingCall, setAddingCall] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const d = await fetchJSON<{ leads: Lead[]; total: number }>(`/leads?limit=200${statusFilter ? `&status=${statusFilter}` : ''}`);
    if (d) { setLeads(d.leads); setTotal(d.total); }
    setLoading(false);
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const loadDetail = async (leadId: number) => {
    setSelectedLeadId(leadId); setDetailLoading(true); setDetail(null);
    const d = await fetchJSON<LeadFullDetail>(`/crm/leads/${leadId}/full-detail`);
    if (d) setDetail(d);
    setDetailLoading(false);
  };

  const logCall = async () => {
    if (!selectedLeadId) return;
    setAddingCall(true);
    await postJSON('/crm/calls', { lead_id: selectedLeadId, outcome: callForm.outcome, duration_minutes: parseInt(callForm.duration_minutes) || null, notes: callForm.notes, follow_up_required: callForm.follow_up_required });
    setCallForm({ outcome: 'connected', duration_minutes: '', notes: '', follow_up_required: false });
    await loadDetail(selectedLeadId);
    setAddingCall(false);
  };

  const statuses = ['', 'new', 'scored', 'contacted', 'replied', 'meeting_booked', 'proposal_sent', 'closed_won', 'closed_lost'];
  const filtered = leads.filter(l => !search || String(l.id).includes(search) || l.company_name?.toLowerCase().includes(search.toLowerCase()) || l.contact_name?.toLowerCase().includes(search.toLowerCase()) || l.status?.includes(search.toLowerCase()));

  return (
    <>
      <div className="page-header">
        <div><div className="page-title">📋 CRM & Activity Tracking</div><div className="page-subtitle">Complete audit trail — every interaction automatically logged ({total} leads)</div></div>
      </div>

      <div className="grid-1-2" style={{ alignItems: 'start' }}>
        {/* Lead List Panel */}
        <div className="card" style={{ maxHeight: '85vh', overflowY: 'auto' }}>
          <div className="card-title" style={{ marginBottom: 16 }}>Leads</div>
          <div style={{ display: 'flex', gap: 10, marginBottom: 16 }}>
            <input placeholder="Search leads..." value={search} onChange={e => setSearch(e.target.value)} style={{ flex: 1 }} />
            <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ width: 'auto' }}>
              {statuses.map(s => <option key={s} value={s}>{s || 'All Status'}</option>)}
            </select>
          </div>
          {loading ? <Spinner /> : filtered.length === 0 ? (
            <div className="empty-state">No leads found.</div>
          ) : filtered.map(l => (
            <div key={l.id} onClick={() => loadDetail(l.id)} style={{ padding: '12px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 8, background: selectedLeadId === l.id ? 'rgba(99,102,241,0.15)' : 'var(--bg-card-hover)', border: `1px solid ${selectedLeadId === l.id ? 'rgba(99,102,241,0.4)' : 'transparent'}`, transition: 'all 0.2s' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontWeight: 600, fontSize: 14, color: selectedLeadId === l.id ? 'var(--accent-glow)' : 'var(--text-primary)' }}>{getLeadDisplayName(l)}</span>
                <StatusBadge status={l.status} />
              </div>
              <div style={{ display: 'flex', gap: 10, marginTop: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                {l.lead_score != null && <ScoreBar score={l.lead_score} />}
                {l.priority && <StatusBadge status={l.priority} />}
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{timeAgo(l.last_activity_at)}</span>
              </div>
            </div>
          ))}
        </div>

        {/* Detail Panel */}
        <div>
          {!selectedLeadId ? (
            <div className="card"><div className="empty-state">← Select a lead to view complete CRM details</div></div>
          ) : detailLoading ? (
            <div className="card"><Spinner /></div>
          ) : detail ? (
            <>
              {/* Lead Header */}
              <div className="card" style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 20 }}>Lead #{detail.lead.id} — {detail.company?.name || 'Unnamed Company'}</div>
                    {detail.company && <div style={{ fontSize: 15, color: 'var(--text-secondary)', marginTop: 6 }}>{detail.company.org_type || detail.company.industry || 'Healthcare'}</div>}
                    {detail.company?.industry && <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>{detail.company.city || ''} {detail.company.state || ''} {detail.company.country || ''}</div>}
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, alignItems: 'flex-end' }}>
                    <StatusBadge status={detail.lead.status} />
                    <StatusChanger leadId={detail.lead.id} currentStatus={detail.lead.status || ''} onChange={() => loadDetail(selectedLeadId!)} />
                    {detail.lead.lead_score != null && <ScoreBar score={detail.lead.lead_score} />}
                    {detail.lead.priority && <StatusBadge status={detail.lead.priority} />}
                  </div>
                </div>

                {detail.contact && (
                  <div className="info-grid" style={{ marginTop: 20, paddingTop: 20, borderTop: '1px solid var(--border)' }}>
                    <div className="info-item"><span className="info-label">Name</span><span className="info-value">{detail.contact.first_name} {detail.contact.last_name}</span></div>
                    <div className="info-item"><span className="info-label">Title</span><span className="info-value">{detail.contact.title || '—'}</span></div>
                    <div className="info-item"><span className="info-label">Email</span><span className="info-value" style={{ fontSize: 13 }}>{detail.contact.email}</span></div>
                    <div className="info-item"><span className="info-label">Phone</span><span className="info-value">{detail.contact.phone || '—'}</span></div>
                    {detail.contact.linkedin_url && <div className="info-item" style={{ gridColumn: '1 / -1' }}><span className="info-label">LinkedIn</span><a href={detail.contact.linkedin_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-glow)', fontSize: 13 }}>{detail.contact.linkedin_url}</a></div>}
                  </div>
                )}
              </div>

              {/* Tabs */}
              <div className="card">
                <div className="tab-bar" style={{ marginBottom: 20 }}>
                  {(['timeline', 'emails', 'signals', 'calls', 'intelligence'] as const).map(t => (
                    <div key={t} className={`tab ${detailTab === t ? 'active' : ''}`} onClick={() => setDetailTab(t)}>
                      {t === 'timeline' ? `Timeline (${detail.activities.length})` : t === 'emails' ? `Emails (${detail.emails.length})` : t === 'signals' ? `Signals (${detail.signals.length})` : t === 'calls' ? `Calls (${detail.calls.length})` : `Intelligence 🧠`}
                    </div>
                  ))}
                </div>

                {detailTab === 'timeline' && (
                  <div className="timeline">
                    {detail.activities.length === 0 ? <div className="empty-state">No activities yet.</div> : detail.activities.map(a => (
                      <div key={a.id} className="timeline-item">
                        <div>
                          <div className="timeline-type">{a.type}</div>
                          <div className="timeline-desc">{a.description}</div>
                          <div className="timeline-time">{fmtDate(a.created_at)}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {detailTab === 'emails' && (
                  <>
                    {detail.emails.length === 0 ? <div className="empty-state">No emails yet.</div> : detail.emails.map(e => (
                      <div key={e.id} style={{ padding: '16px', background: 'var(--bg-card-hover)', borderRadius: 8, marginBottom: 12 }}>
                        <div style={{ fontWeight: 600, fontSize: 14 }}>{e.subject}</div>
                        <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
                          <StatusBadge status={e.status} />
                          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>To: {e.to_email}</span>
                          {e.opened_at && <span style={{ fontSize: 12, color: 'var(--green)' }}>Opened ✓</span>}
                          {e.replied_at && <span style={{ fontSize: 12, color: 'var(--cyan)' }}>Replied ✓</span>}
                        </div>
                        <div style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 10, whiteSpace: 'pre-wrap', maxHeight: 150, overflow: 'hidden' }}>{e.body}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>{fmtDate(e.sent_at)}</div>
                      </div>
                    ))}
                  </>
                )}

                {detailTab === 'signals' && (
                  <>
                    {detail.signals.length === 0 ? <div className="empty-state">No signals. Run signal detection first.</div> : detail.signals.map(s => (
                      <div key={s.id} className="signal-card">
                        <div className="signal-card-type">{s.type?.replace(/_/g, ' ')}</div>
                        <div className="signal-card-desc">{s.description}</div>
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>{fmtDate(s.created_at)}</div>
                      </div>
                    ))}
                  </>
                )}

                {detailTab === 'calls' && (
                  <>
                    {/* Log Call Form */}
                    <div style={{ background: 'var(--bg-card-hover)', borderRadius: 8, padding: 16, marginBottom: 20 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 14 }}>Log New Call</div>
                      <div className="form-row form-row-2" style={{ marginBottom: 12 }}>
                        <div className="form-group">
                          <label className="form-label">Outcome</label>
                          <select value={callForm.outcome} onChange={e => setCallForm(f => ({ ...f, outcome: e.target.value }))}>
                            <option value="connected">Connected</option>
                            <option value="voicemail">Voicemail</option>
                            <option value="no_answer">No Answer</option>
                            <option value="meeting_booked">Meeting Booked</option>
                            <option value="follow_up">Follow-up Required</option>
                          </select>
                        </div>
                        <div className="form-group">
                          <label className="form-label">Duration (min)</label>
                          <input type="number" placeholder="e.g. 15" value={callForm.duration_minutes} onChange={e => setCallForm(f => ({ ...f, duration_minutes: e.target.value }))} />
                        </div>
                      </div>
                      <div className="form-group" style={{ marginBottom: 12 }}>
                        <label className="form-label">Notes</label>
                        <textarea placeholder="Call notes..." value={callForm.notes} onChange={e => setCallForm(f => ({ ...f, notes: e.target.value }))} style={{ minHeight: 70 }} />
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
                        <input type="checkbox" id="followup" checked={callForm.follow_up_required} onChange={e => setCallForm(f => ({ ...f, follow_up_required: e.target.checked }))} style={{ width: 'auto' }} />
                        <label htmlFor="followup" style={{ fontSize: 14, color: 'var(--text-secondary)', cursor: 'pointer' }}>Follow-up Required</label>
                      </div>
                      <button className="btn btn-primary" onClick={logCall} disabled={addingCall}>
                        {addingCall ? 'Logging...' : '📞 Log Call'}
                      </button>
                    </div>

                    {detail.calls.length === 0 ? <div className="empty-state">No calls logged.</div> : detail.calls.map(c => (
                      <div key={c.id} style={{ padding: '16px', background: 'var(--bg-card-hover)', borderRadius: 8, marginBottom: 10 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                          <div style={{ fontWeight: 600, fontSize: 14 }}>{c.outcome?.replace(/_/g, ' ') || 'Call'}</div>
                          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{c.duration_minutes ? `${c.duration_minutes} min` : ''}</span>
                        </div>
                        {c.notes && <div style={{ fontSize: 14, color: 'var(--text-secondary)', marginTop: 8 }}>{c.notes}</div>}
                        {c.follow_up_required && <span className="badge badge-amber" style={{ marginTop: 8 }}>Follow-up Required</span>}
                        <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8 }}>{fmtDate(c.call_date)}</div>
                      </div>
                    ))}
                  </>
                )}

                {detailTab === 'intelligence' && detail.company && (
                  <CompanyIntelligenceTab companyId={detail.company.id} />
                )}

              </div>
            </>
          ) : (
            <div className="card"><div className="empty-state">Failed to load detail.</div></div>
          )}
        </div>
      </div>
    </>
  );
}

