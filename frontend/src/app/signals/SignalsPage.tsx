import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';


export default function SignalsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLead, setSelectedLead] = useState<Lead | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [scanning, setScanning] = useState(false);
  const [scanResult, setScanResult] = useState<any>(null);

  useEffect(() => {
    fetchJSON<{ leads: Lead[]; total: number }>('/leads?limit=200').then(d => { if (d) setLeads(d.leads); });
  }, []);

  const loadSignals = async (lead: Lead) => {
    setSelectedLead(lead);
    setScanResult(null);
    const data = await fetchJSON<any>(`/signals/list/${lead.id}`);
    if (data) setSignals(data.signals || []);
  };

  const scanNow = async () => {
    if (!selectedLead) return;
    setScanning(true);
    const res = await postJSON<any>(`/signals/scan/${selectedLead.id}`);
    setScanResult(res);
    if (res) {
      const data = await fetchJSON<any>(`/signals/list/${selectedLead.id}`);
      if (data) setSignals(data.signals || []);
      setLeads(prev => prev.map(l => l.id === selectedLead.id ? { ...l, lead_score: res.score, priority: res.priority, status: 'scored' } : l));
      setSelectedLead(prev => prev ? { ...prev, lead_score: res.score, priority: res.priority } : prev);
    }
    setScanning(false);
  };

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">📡 Sales Intelligence</div>
          <div className="page-subtitle">AI-powered analysis of public buying signals per lead</div>
        </div>
        {selectedLead && (
          <button className="btn btn-primary" onClick={scanNow} disabled={scanning}>
            {scanning ? <><div className="spinner" style={{ width: 16, height: 16, margin: 0 }} />Scanning...</> : '⚡ Run Intelligence Scan'}
          </button>
        )}
      </div>

      <div className="grid-1-2" style={{ alignItems: 'start' }}>
        <div className="card" style={{ maxHeight: '80vh', overflowY: 'auto' }}>
          <div className="card-title" style={{ marginBottom: 16 }}>Intelligence Target</div>
          {leads.length === 0 ? <div className="empty-state">No leads yet. Run Prospecting first.</div> :
            leads.map(l => (
              <div key={l.id} onClick={() => loadSignals(l)} style={{ padding: '12px 14px', borderRadius: 8, cursor: 'pointer', marginBottom: 6, background: selectedLead?.id === l.id ? 'rgba(99,102,241,0.15)' : 'transparent', border: selectedLead?.id === l.id ? '1px solid rgba(99,102,241,0.3)' : '1px solid transparent', transition: 'all 0.2s' }}>
                <div style={{ fontWeight: 600, fontSize: 14, color: selectedLead?.id === l.id ? 'var(--accent-glow)' : 'var(--text-primary)' }}>{getLeadDisplayName(l)}</div>
                <div style={{ display: 'flex', gap: 10, marginTop: 6, alignItems: 'center' }}>
                  <StatusBadge status={l.status} />
                  {l.lead_score != null && <ScoreBar score={l.lead_score} />}
                  {l.priority && <StatusBadge status={l.priority} />}
                </div>
              </div>
            ))
          }
        </div>

        <div>
          {!selectedLead ? (
            <div className="card"><div className="empty-state">← Select a lead to view buying signals</div></div>
          ) : (
            <>
              {/* TOP SECTION: SUMMARY & SCORES */}
              <div className="card" style={{ marginBottom: 20 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                  <div style={{ fontSize: 20, fontWeight: 700 }}>{getLeadDisplayName(selectedLead)}</div>
                  <div style={{ display: 'flex', gap: 16, alignItems: 'center' }}>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>Buying Score</div>
                      <div style={{ fontSize: 24, fontWeight: 700, color: 'var(--green)' }}>{selectedLead.lead_score || 0}</div>
                    </div>
                    <div style={{ textAlign: 'center' }}>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 4 }}>Priority</div>
                      <StatusBadge status={selectedLead.priority || 'N/A'} />
                    </div>
                  </div>
                </div>

                {scanResult && !scanResult.skipped && (
                  <div style={{ padding: '12px 16px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 8, fontSize: 14, color: 'var(--green)' }}>
                    ✓ Scan complete — Score: {scanResult.score}, Priority: {scanResult.priority}, Signals: {scanResult.signals_created}
                  </div>
                )}
                {scanResult?.skipped && (
                  <div style={{ padding: '12px 16px', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)', borderRadius: 8, fontSize: 14, color: 'var(--amber)' }}>
                    ℹ Already scanned today. Run tomorrow for fresh signals.
                  </div>
                )}
              </div>

              {/* MIDDLE SECTION: CHRONOLOGICAL TIMELINE OF SIGNALS */}
              <div className="card" style={{ marginBottom: 20 }}>
                <div className="card-title" style={{ marginBottom: 16 }}>Signal Intelligence Timeline ({signals.length})</div>
                {signals.length === 0 ? (
                  <div className="empty-state">No signals detected yet. Click "Run Intelligence Scan" to analyze.</div>
                ) : (
                  <div className="timeline" style={{ marginLeft: 6 }}>
                    {signals.map(s => (
                      <div key={s.id} className="timeline-item" style={{ paddingLeft: 24, paddingBottom: 32 }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                            <div className="badge badge-amber">{s.signal_type?.replace(/_/g, ' ') || s.type?.replace(/_/g, ' ') || 'Signal'}</div>
                            {s.confidence_score != null && (
                              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Confidence: <span style={{ color: 'var(--green)', fontWeight: 600 }}>{s.confidence_score}%</span></div>
                            )}
                          </div>
                          <div className="timeline-time">{fmtDate(s.published_date || s.created_at)}</div>
                        </div>

                        <div style={{ marginTop: 12, fontWeight: 700, fontSize: 16, color: 'var(--text-primary)' }}>
                          {s.headline || 'Detected Signal'}
                        </div>

                        <div style={{ marginTop: 8, fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                          {s.description}
                        </div>

                        {(s.business_impact || s.why_it_matters) && (
                          <div style={{ marginTop: 16, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, background: 'var(--bg-card-hover)', padding: 16, borderRadius: 8, border: '1px solid var(--border)' }}>
                            {s.business_impact && (
                              <div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>Business Impact</div>
                                <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{s.business_impact}</div>
                              </div>
                            )}
                            {s.why_it_matters && (
                              <div>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 700, marginBottom: 6 }}>Why It Matters to Us</div>
                                <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{s.why_it_matters}</div>
                              </div>
                            )}
                          </div>
                        )}

                        <div style={{ marginTop: 12, display: 'flex', gap: 16, fontSize: 12 }}>
                          {(s.source_url || s.evidence_url) && (
                            <a href={s.source_url || s.evidence_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent-glow)', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
                              View Source ↗
                            </a>
                          )}
                          {s.source_name && (
                            <span style={{ color: 'var(--text-muted)' }}>Source: {s.source_name}</span>
                          )}
                          {s.icp_match != null && (
                            <span style={{ color: 'var(--text-muted)' }}>ICP Match: <span style={{ color: s.icp_match > 70 ? 'var(--green)' : 'var(--amber)', fontWeight: 600 }}>{s.icp_match}%</span></span>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* BOTTOM SECTION: RECOMMENDATIONS (AI Generated if signals exist) */}
              {signals.length > 0 && signals[0].target_persona && (
                 <div className="card" style={{ borderColor: 'var(--accent)' }}>
                   <div className="card-title" style={{ color: 'var(--accent-glow)' }}>AI Sales Recommendations</div>
                   <div className="grid-2" style={{ marginBottom: 0 }}>
                     <div>
                       <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Target Persona</div>
                       <div style={{ fontWeight: 600, color: 'var(--text-primary)', marginBottom: 16 }}>{signals[0].target_persona}</div>
                       <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Suggested Action</div>
                       <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{signals[0].recommended_action || 'Engage Lead'}</div>
                     </div>
                     <div>
                       <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>Suggested Pitch Angle</div>
                       <div style={{ background: 'var(--bg-primary)', padding: '12px', borderRadius: 8, fontStyle: 'italic', fontSize: 13, color: 'var(--text-secondary)' }}>
                         "{signals[0].suggested_pitch || 'Mention recent company changes to personalize outreach.'}"
                       </div>
                     </div>
                   </div>
                 </div>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}

