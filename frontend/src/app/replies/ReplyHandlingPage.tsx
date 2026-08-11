import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';


export default function RepliesPage() {
  const [inbox, setInbox] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedLead, setSelectedLead] = useState<number | null>(null);
  const [timeline, setTimeline] = useState<any[]>([]);
  const [timelineLoading, setTimelineLoading] = useState(false);
  const [composerOpen, setComposerOpen] = useState(false);
  const [draftReply, setDraftReply] = useState('');
  const [sending, setSending] = useState(false);
  const [selectedReplyId, setSelectedReplyId] = useState<number | null>(null);

  const loadInbox = async () => {
    setLoading(true);
    const data = await fetchJSON<any[]>('/replies/inbox');
    if (data) setInbox(data);
    setLoading(false);
  };

  useEffect(() => { loadInbox(); }, []);

  const loadTimeline = async (leadId: number) => {
    setTimelineLoading(true);
    setSelectedLead(leadId);
    const data = await fetchJSON<any[]>(`/replies/inbox/${leadId}/history`);
    if (data) setTimeline(data);
    setTimelineLoading(false);
    setComposerOpen(false);
    setDraftReply('');
    setSelectedReplyId(null);
  };

  const handleAction = async (replyId: number, action: string) => {
    await postJSON(`/replies/${replyId}/action`, { action });
    if (selectedLead) loadTimeline(selectedLead);
    loadInbox();
  };

  const handleSendReply = async () => {
    if (!selectedReplyId || !draftReply.trim()) return;
    setSending(true);
    await postJSON(`/replies/${selectedReplyId}/respond`, { body: draftReply });
    setSending(false);
    setComposerOpen(false);
    setDraftReply('');
    if (selectedLead) loadTimeline(selectedLead);
    loadInbox();
  };

  const activeLead = inbox.find(l => l.lead_id === selectedLead);
  
  // Find the most recent reply's analysis for the Insights pane
  const latestReply = timeline.slice().reverse().find(t => t.type === 'reply');
  const analysis = latestReply?.data?.analysis;

  return (
    <div style={{ display: 'flex', height: 'calc(100vh - 64px)', overflow: 'hidden', margin: '-20px' }}>
      {/* LEFT PANEL - LEADS */}
      <div style={{ width: 350, borderRight: '1px solid var(--border)', background: 'var(--bg)', display: 'flex', flexDirection: 'column' }}>
        <div style={{ padding: '20px', borderBottom: '1px solid var(--border)' }}>
          <h2 style={{ fontSize: 18, margin: '0 0 10px 0' }}>Conversation Inbox</h2>
          <button className="btn btn-primary" onClick={loadInbox} style={{ width: '100%' }}>↻ Refresh Inbox</button>
        </div>
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {loading ? <Spinner /> : inbox.length === 0 ? (
            <div style={{ padding: 20, textAlign: 'center', color: 'var(--text-muted)' }}>No leads with active replies.</div>
          ) : inbox.map(lead => (
            <div 
              key={lead.lead_id} 
              onClick={() => loadTimeline(lead.lead_id)}
              style={{ 
                padding: '16px', 
                borderBottom: '1px solid var(--border)', 
                cursor: 'pointer',
                background: selectedLead === lead.lead_id ? 'rgba(0,0,0,0.2)' : 'transparent',
                transition: 'background 0.2s'
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <strong style={{ fontSize: 15 }}>{lead.lead_name}</strong>
                {lead.unread_count > 0 && <span className="badge badge-primary">{lead.unread_count} new</span>}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 8 }}>{lead.company_name} • {lead.email}</div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {lead.priority && <span className="badge badge-amber">{lead.priority} Priority</span>}
                {lead.intent && <StatusBadge status={lead.intent} />}
                {lead.sentiment && <StatusBadge status={lead.sentiment} />}
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-secondary)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {lead.clean_body || 'No message content...'}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, textAlign: 'right' }}>
                {timeAgo(lead.latest_reply_time)}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* RIGHT AREA - CONVERSATION & INSIGHTS */}
      <div style={{ flex: 1, display: 'flex', background: 'var(--bg-secondary)' }}>
        {!selectedLead ? (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
            Select a lead to view the conversation timeline.
          </div>
        ) : (
          <>
            {/* CENTER PANEL - TIMELINE */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', borderRight: '1px solid var(--border)' }}>
              <div style={{ padding: '20px', borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
                <h3 style={{ margin: '0 0 4px 0' }}>{activeLead?.lead_name}</h3>
                <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>{activeLead?.email} • {activeLead?.company_name}</div>
              </div>
              
              <div style={{ flex: 1, overflowY: 'auto', padding: '20px' }}>
                {timelineLoading ? <Spinner /> : timeline.length === 0 ? (
                  <div style={{ color: 'var(--text-muted)', textAlign: 'center' }}>No timeline events found.</div>
                ) : (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                    {timeline.map((item, i) => (
                      <div key={i} style={{ 
                        background: 'var(--bg)', 
                        padding: '16px', 
                        borderRadius: 8, 
                        border: '1px solid var(--border)',
                        position: 'relative',
                        marginLeft: item.type === 'reply' ? 0 : 32,
                        marginRight: item.type === 'email' ? 0 : 32,
                      }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                          <div style={{ fontWeight: 600, display: 'flex', alignItems: 'center', gap: 8 }}>
                            {item.type === 'reply' && '📥 Reply Received'}
                            {item.type === 'email' && '📤 Outbound Email'}
                            {item.type === 'meeting' && '📅 Meeting'}
                            {item.type === 'activity' && '⚡ Activity'}
                            {item.type === 'note' && '📝 Note'}
                            {item.type === 'call' && '📞 Call'}
                          </div>
                          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{timeAgo(item.timestamp)}</div>
                        </div>
                        
                        {item.type === 'reply' && (
                          <>
                            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{item.data.subject}</div>
                            <div className="email-preview" style={{ marginBottom: 12 }}>{item.data.body}</div>
                            <div style={{ display: 'flex', gap: 8, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                              <button className="btn btn-ghost" onClick={() => {
                                setDraftReply(item.data.analysis?.reply_draft || '');
                                setSelectedReplyId(item.data.id);
                                setComposerOpen(true);
                              }}>💬 Reply</button>
                              <button className="btn btn-ghost" onClick={() => handleAction(item.data.id, 'mark_read')}>✓ Mark Read</button>
                              <button className="btn btn-ghost" onClick={() => handleAction(item.data.id, 'archive')}>🗃️ Archive</button>
                            </div>
                          </>
                        )}
                        
                        {item.type === 'email' && (
                          <>
                            <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{item.data.subject}</div>
                            <div className="email-preview">{item.data.body}</div>
                          </>
                        )}
                        
                        {item.type === 'activity' && (
                          <div style={{ fontSize: 14 }}>{item.data.description}</div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
              
              {/* COMPOSER */}
              {composerOpen && selectedReplyId && (
                <div style={{ borderTop: '1px solid var(--border)', background: 'var(--bg)', padding: '20px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
                    <div style={{ fontWeight: 600 }}>Draft Reply</div>
                    <button className="btn btn-ghost" onClick={() => setComposerOpen(false)} style={{ padding: '4px 8px' }}>✕</button>
                  </div>
                  <textarea 
                    className="input" 
                    rows={5} 
                    value={draftReply}
                    onChange={e => setDraftReply(e.target.value)}
                    style={{ width: '100%', marginBottom: 12 }}
                  />
                  <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                    <button className="btn btn-ghost" onClick={() => setComposerOpen(false)}>Cancel</button>
                    <button className="btn btn-primary" onClick={handleSendReply} disabled={sending}>
                      {sending ? 'Sending...' : 'Send Email'}
                    </button>
                  </div>
                </div>
              )}
            </div>

            {/* RIGHT PANEL - INSIGHTS */}
            <div style={{ width: 300, background: 'var(--bg)', padding: '20px', overflowY: 'auto' }}>
              <h3 style={{ margin: '0 0 20px 0' }}>AI Insights</h3>
              {analysis ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600 }}>Intent</div>
                    <StatusBadge status={analysis.intent} />
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600 }}>Sentiment</div>
                    <StatusBadge status={analysis.sentiment} />
                  </div>
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600 }}>Priority</div>
                    <span className="badge badge-amber">{analysis.priority}</span>
                  </div>
                  {analysis.objections && (() => {
                    try {
                      const obs = JSON.parse(analysis.objections);
                      if (obs.length > 0) {
                        return (
                          <div>
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600 }}>Objections</div>
                            <ul style={{ margin: 0, paddingLeft: 20, fontSize: 13, color: 'var(--amber)' }}>
                              {obs.map((o: string, i: number) => <li key={i}>{o}</li>)}
                            </ul>
                          </div>
                        );
                      }
                    } catch (e) {}
                    return null;
                  })()}
                  <div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', fontWeight: 600 }}>Recommended Action</div>
                    <div style={{ fontSize: 13, color: 'var(--text-primary)', background: 'rgba(255,255,255,0.05)', padding: 12, borderRadius: 6 }}>
                      {analysis.recommended_action || 'Review manually'}
                    </div>
                  </div>
                  {analysis.reply_draft && (
                    <div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', fontWeight: 600 }}>AI Draft Proposal</div>
                      <button className="btn btn-green" style={{ width: '100%' }} onClick={() => {
                        setDraftReply(analysis.reply_draft);
                        setSelectedReplyId(latestReply?.data?.id || null);
                        setComposerOpen(true);
                      }}>
                        📝 Use AI Draft
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No analysis available for this conversation.</div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

