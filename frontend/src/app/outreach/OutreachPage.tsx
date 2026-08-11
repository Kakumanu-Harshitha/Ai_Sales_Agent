import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';


export default function OutreachPage() {
  const [tab, setTab] = useState<'generate' | 'campaigns' | 'templates'>('generate');
  const [leads, setLeads] = useState<Lead[]>([]);
  const [selectedLeadId, setSelectedLeadId] = useState<number | ''>('');
  const [channel, setChannel] = useState('email');
  const [generating, setGenerating] = useState(false);
  const [generatingAgain, setGeneratingAgain] = useState(false);
  const [generated, setGenerated] = useState<any>(null);
  const [sendingId, setSendingId] = useState<number | null>(null);
  const [sendResult, setSendResult] = useState<any>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [emails, setEmails] = useState<EmailRecord[]>([]);
  const [leadDetail, setLeadDetail] = useState<LeadFullDetail | null>(null);
  const [signatures, setSignatures] = useState<SignatureTemplate[]>([]);
  const [uploading, setUploading] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [editingSig, setEditingSig] = useState<Partial<SignatureTemplate> | null>(null);
  const [activeEmailId, setActiveEmailId] = useState<number | null>(null);
  const [savingStatus, setSavingStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const activeEmail = activeEmailId ? emails.find(e => e.id === activeEmailId) : emails[0];
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Message Template State
  const [templateSubTab, setTemplateSubTab] = useState<'message' | 'branding'>('message');
  const [outreachTemplates, setOutreachTemplates] = useState<any[]>([]);
  const [selectedTemplateId, setSelectedTemplateId] = useState<number | ''>('');
  const [templateSearch, setTemplateSearch] = useState('');
  const [templateCategory, setTemplateCategory] = useState('');
  const [editingTemplate, setEditingTemplate] = useState<any | null>(null);
  const [previewTemplate, setPreviewTemplate] = useState<any | null>(null);

  const loadSignatures = async () => {
    const data = await fetchJSON<SignatureTemplate[]>('/outreach/signatures');
    if (data) setSignatures(data);
  };

  const loadOutreachTemplates = async () => {
    const data = await fetchJSON<any[]>('/outreach/templates');
    if (data) {
      setOutreachTemplates(data);
      const def = data.find((t: any) => t.is_set_as_default);
      if (def && !selectedTemplateId) setSelectedTemplateId(def.id);
    }
  };

  const deleteOutreachTemplate = async (id: number) => {
    if (!confirm('Delete this template?')) return;
    await fetch(`${API}/outreach/templates/${id}`, { method: 'DELETE' });
    await loadOutreachTemplates();
  };

  const duplicateTemplate = async (id: number) => {
    await fetch(`${API}/outreach/templates/${id}/duplicate`, { method: 'POST' });
    await loadOutreachTemplates();
  };

  const setAsDefaultTemplate = async (id: number) => {
    await fetch(`${API}/outreach/templates/${id}/set_default`, { method: 'POST' });
    await loadOutreachTemplates();
  };

  const saveOutreachTemplate = async () => {
    if (!editingTemplate) return;
    const method = editingTemplate.id ? 'PUT' : 'POST';
    const url = editingTemplate.id ? `/outreach/templates/${editingTemplate.id}` : `/outreach/templates`;
    await fetch(`${API}${url}`, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editingTemplate) });
    setEditingTemplate(null);
    await loadOutreachTemplates();
  };

  useEffect(() => {
    fetchJSON<{ leads: Lead[]; total: number }>('/leads?limit=200').then(d => { if (d) setLeads(d.leads); });
    fetchJSON<Campaign[]>('/outreach/campaigns').then(d => { if (d) setCampaigns(d); });
    loadSignatures();
    loadOutreachTemplates();
  }, []);

  const getImgSrc = (url: string | undefined | null) => {
    if (!url) return '';
    if (url.startsWith('http') || url.startsWith('data:')) return url;
    return `${API}${url}`;
  };

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>, fieldName: keyof EmailRecord = 'header_image_url') => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    const formData = new FormData();
    formData.append('file', file);
    try {
        const res = await fetch(`${API}/outreach/upload`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (data.url) {
            updateDraft(fieldName, data.url);
        }
    } catch (err) {
        console.error("Upload failed", err);
    }
    setUploading(false);
  };

  const loadEmails = async (leadId: number): Promise<EmailRecord[]> => {
    const d = await fetchJSON<EmailRecord[]>(`/outreach/emails/${leadId}`);
    if (d) { setEmails(d); return d; }
    return [];
  };

  const handleLeadSelect = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const id = parseInt(e.target.value);
    setSelectedLeadId(id || '');
    setGenerated(null); setSendResult(null); setLeadDetail(null); setActiveEmailId(null);
    if (id) {
        loadEmails(id);
        const detail = await fetchJSON<LeadFullDetail>(`/crm/leads/${id}/full-detail`);
        if (detail) setLeadDetail(detail);
    }
  };

  // Normal generate (idempotent — returns existing draft for same lead+template)
  const generate = async () => {
    if (!selectedLeadId) return;
    setGenerating(true); setGenerated(null); setSendResult(null);
    const lead = leads.find(l => l.id === selectedLeadId);
    const res = await postJSON<any>('/outreach/generate', {
      lead_id: selectedLeadId,
      channel,
      template_id: selectedTemplateId || null,
      signal_summary: `Lead score: ${lead?.lead_score || 'N/A'}, Priority: ${lead?.priority || 'N/A'}`,
      force_new: false,
    });
    setGenerated(res);
    if (selectedLeadId) {
      const fresh = await loadEmails(Number(selectedLeadId));
      if (res?.email_id) setActiveEmailId(res.email_id);
      else if (fresh.length > 0) setActiveEmailId(fresh[0].id);
    }
    setGenerating(false);
  };

  // Generate Again — always creates a brand new draft, preserving history
  const generateAgain = async () => {
    if (!selectedLeadId) return;
    setGeneratingAgain(true); setSendResult(null);
    const lead = leads.find(l => l.id === selectedLeadId);
    const res = await postJSON<any>('/outreach/generate', {
      lead_id: selectedLeadId,
      channel,
      template_id: selectedTemplateId || null,
      signal_summary: `Lead score: ${lead?.lead_score || 'N/A'}, Priority: ${lead?.priority || 'N/A'}`,
      force_new: true,
    });
    setGenerated(res);
    if (selectedLeadId) {
      const fresh = await loadEmails(Number(selectedLeadId));
      if (res?.email_id) setActiveEmailId(res.email_id);
      else if (fresh.length > 0) setActiveEmailId(fresh[0].id);
    }
    setGeneratingAgain(false);
  };

  const updateDraftFields = (updates: Partial<EmailRecord>) => {
    const targetId = activeEmailId || (emails[0] ? emails[0].id : null);
    if (!targetId) return;

    // Optimistic UI update
    setEmails(prev => {
      const copy = [...prev];
      const idx = copy.findIndex(e => e.id === targetId);
      if (idx !== -1) copy[idx] = { ...copy[idx], ...updates };
      return copy;
    });

    setSavingStatus('saving');
    if ((window as any).saveTimer) clearTimeout((window as any).saveTimer);
    (window as any).saveTimer = setTimeout(async () => {
      try {
        const res = await fetch(`${API}/outreach/emails/${targetId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updates)
        });
        const data = res.ok ? await res.json() : null;
        // Update html_body from backend (single source of truth for rendering)
        if (data && data.html_body) {
          setEmails(prev => {
            const copy = [...prev];
            const idx = copy.findIndex(e => e.id === targetId);
            if (idx !== -1) copy[idx] = { ...copy[idx], html_body: data.html_body };
            return copy;
          });
        }
        setSavingStatus('saved');
        setTimeout(() => setSavingStatus('idle'), 2000);
      } catch (err) {
        console.error("Auto-save failed", err);
        setSavingStatus('idle');
      }
    }, 600);
  };

  const updateDraft = (key: keyof EmailRecord, val: any) => {
    updateDraftFields({ [key]: val });
  };

  const sendEmail = async (emailId: number) => {
    setSendingId(emailId);
    const draft = emails.find(e => e.id === emailId);
    // Always send current editor state so branding fields are included
    const payload = draft ? {
        subject: draft.subject,
        body: draft.body,
        header_image_url: draft.header_image_url,
        signature_template_id: draft.signature_template_id,
        full_name: draft.full_name,
        designation: draft.designation,
        department: draft.department,
        company: draft.company,
        sender_email: draft.sender_email,
        phone: draft.phone,
        website: draft.website,
        linkedin: draft.linkedin,
        address: draft.address,
        logo_url: draft.logo_url,
        digital_signature_url: draft.digital_signature_url,
        footer_banner_url: draft.footer_banner_url
    } : {};
    const res = await postJSON<any>(`/outreach/send/${emailId}`, payload);
    setSendResult(res);
    setSendingId(null);
    if (selectedLeadId) loadEmails(Number(selectedLeadId));
  };

  const selectedTemplate = outreachTemplates.find(t => t.id === selectedTemplateId);

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">📧 Outreach Agent</div>
          <div className="page-subtitle">AI-generated personalized outreach using live SETV knowledge, lead context, and buying signals</div>
        </div>
      </div>
      <div className="tab-bar">
        <div className={`tab ${tab === 'generate' ? 'active' : ''}`} onClick={() => setTab('generate')}>Generate Outreach</div>
        <div className={`tab ${tab === 'campaigns' ? 'active' : ''}`} onClick={() => setTab('campaigns')}>Campaigns ({campaigns.length})</div>
        <div className={`tab ${tab === 'templates' ? 'active' : ''}`} onClick={() => setTab('templates')}>Branding Templates</div>
      </div>

      {tab === 'generate' && (
        <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: 20, alignItems: 'start' }}>

          {/* ── LEFT PANEL: Controls + History ── */}
          <div>
            <div className="card" style={{ marginBottom: 20 }}>
              <div className="card-title" style={{ marginBottom: 16 }}>🎯 Configure Outreach</div>

              <div className="form-group" style={{ marginBottom: 14 }}>
                <label className="form-label">Select Lead</label>
                <select value={selectedLeadId} onChange={handleLeadSelect}>
                  <option value="">Choose lead...</option>
                  {leads.map(l => <option key={l.id} value={l.id}>{getLeadDisplayName(l)} — {l.status}{l.lead_score != null ? ` (${l.lead_score})` : ''}</option>)}
                </select>
              </div>

              <div className="form-group" style={{ marginBottom: 14 }}>
                <label className="form-label">Template</label>
                <select value={selectedTemplateId} onChange={e => setSelectedTemplateId(parseInt(e.target.value) || '')}>
                  <option value="">Auto-select (use default)</option>
                  {outreachTemplates.map(t => <option key={t.id} value={t.id}>{t.name}{t.is_set_as_default ? ' ★' : ''} — {t.category}</option>)}
                </select>
                {selectedTemplate && (
                  <div style={{ marginTop: 6, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <span style={{ background: 'rgba(99,102,241,0.15)', color: 'var(--accent-glow)', borderRadius: 4, padding: '2px 8px', fontSize: 11 }}>{selectedTemplate.category}</span>
                    {selectedTemplate.is_default && <span style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--amber)', borderRadius: 4, padding: '2px 8px', fontSize: 11 }}>Built-in</span>}
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center' }}>{selectedTemplate.subject?.slice(0, 40)}</span>
                  </div>
                )}
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Channel</label>
                <select value={channel} onChange={e => setChannel(e.target.value)}>
                  <option value="email">Cold Email</option>
                  <option value="linkedin">LinkedIn Message</option>
                  <option value="follow_up">Follow-up Email</option>
                </select>
              </div>

              <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                <button className="btn btn-primary" onClick={generate} disabled={generating || generatingAgain || !selectedLeadId} style={{ flex: 1 }}>
                  {generating ? <><div className="spinner" style={{ width: 14, height: 14, margin: '0 6px 0 0' }} />Generating...</> : '✨ Generate'}
                </button>
                {emails.length > 0 && selectedLeadId && (
                  <button className="btn btn-secondary" onClick={generateAgain} disabled={generating || generatingAgain} title="Create a new draft variation without overwriting history">
                    {generatingAgain ? <><div className="spinner" style={{ width: 14, height: 14, margin: '0 6px 0 0' }} />...</> : '🔄 Again'}
                  </button>
                )}
              </div>

              {generated && !generated.skipped && (
                <div style={{ marginTop: 12, padding: '10px 12px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 6, fontSize: 13 }}>
                  <span style={{ color: 'var(--green)' }}>✓</span> {generated.reused ? 'Existing draft loaded' : 'New draft created'} (#{generated.email_id})
                  {generated.template_name && <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>· {generated.template_name}</span>}
                </div>
              )}
              {generated?.skipped && (
                <div style={{ marginTop: 12, padding: '10px 12px', background: 'rgba(245,158,11,0.08)', borderRadius: 6, color: 'var(--amber)', fontSize: 13 }}>
                  ⚠️ {generated.reason || 'Skipped'}
                </div>
              )}
              {sendResult && (
                <div style={{ marginTop: 12, padding: '10px 12px', background: sendResult.status === 'sent' ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)', borderRadius: 6, fontSize: 13, color: sendResult.status === 'sent' ? 'var(--green)' : 'var(--red)' }}>
                  {sendResult.status === 'sent' ? `✓ Sent to ${sendResult.to}` : `✗ ${sendResult.error || JSON.stringify(sendResult)}`}
                </div>
              )}
            </div>

            {/* Email History */}
            {emails.length > 0 && (
              <div className="card">
                <div className="card-title" style={{ marginBottom: 12, fontSize: 14 }}>Email History ({emails.length})</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {emails.map(e => {
                    const isActive = (activeEmailId ?? emails[0]?.id) === e.id;
                    return (
                      <div key={e.id}
                           style={{ padding: '12px 14px', background: isActive ? 'rgba(99,102,241,0.08)' : 'var(--bg-card-hover)', border: `1px solid ${isActive ? 'var(--accent-glow)' : 'transparent'}`, borderRadius: 8, cursor: 'pointer', transition: 'all 0.15s' }}
                           onClick={() => setActiveEmailId(e.id)}>
                        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 6, color: 'var(--text-primary)', lineHeight: 1.3 }}>{e.subject || '(No subject)'}</div>
                        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center' }}>
                          <StatusBadge status={e.status} />
                          {e.outreach_template_name && <span style={{ fontSize: 11, background: 'rgba(99,102,241,0.1)', color: 'var(--accent-glow)', borderRadius: 3, padding: '1px 6px' }}>{e.outreach_template_name}</span>}
                          {e.opened_at && <span style={{ fontSize: 11, color: 'var(--green)' }}>Opened ✓</span>}
                          {e.replied_at && <span style={{ fontSize: 11, color: 'var(--cyan)' }}>Replied ✓</span>}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 5 }}>{fmtDate(e.sent_at)} · To: {e.to_email}</div>
                        {e.status === 'failed' && e.error_message && <div style={{ fontSize: 11, color: 'var(--red)', marginTop: 4 }}>✗ {e.error_message}</div>}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* ── RIGHT PANEL: Editor + Preview ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* Empty state */}
            {!activeEmail && !generating && (
              <div className="card">
                <div className="empty-state" style={{ padding: '60px 20px' }}>
                  <div style={{ fontSize: 40, marginBottom: 16 }}>✍️</div>
                  <div style={{ fontWeight: 600, marginBottom: 8 }}>No email generated yet</div>
                  <div style={{ fontSize: 14, color: 'var(--text-muted)' }}>Select a lead and template, then click Generate to create a personalized outreach email.</div>
                </div>
              </div>
            )}

            {/* Generating spinner */}
            {(generating || generatingAgain) && (
              <div className="card" style={{ textAlign: 'center', padding: 40 }}>
                <Spinner />
                <div style={{ marginTop: 16, color: 'var(--text-muted)', fontSize: 14 }}>Generating personalized email using SETV knowledge base and lead context...</div>
              </div>
            )}

            {/* Email Editor — always shown when email selected */}
            {activeEmail && !generating && !generatingAgain && (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                  <div className="card-title" style={{ margin: 0 }}>✏️ Email Editor</div>
                  <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                    {savingStatus === 'saving' && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Saving...</span>}
                    {savingStatus === 'saved' && <span style={{ fontSize: 12, color: 'var(--green)' }}>✓ Saved</span>}
                    <StatusBadge status={activeEmail.status} />
                  </div>
                </div>

                {/* Header Banner */}
                <div style={{ marginBottom: 16, padding: 14, border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Header Banner</div>
                  {activeEmail.header_image_url ? (
                    <div>
                      <img src={getImgSrc(activeEmail.header_image_url)} alt="Header" style={{ maxWidth: '100%', maxHeight: 120, borderRadius: 6, objectFit: 'cover', display: 'block', marginBottom: 8 }} />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <label className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: 12, cursor: 'pointer', margin: 0 }}>Replace<input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'header_image_url')} /></label>
                        <button className="btn btn-ghost" onClick={() => updateDraft('header_image_url', '')} style={{ color: 'var(--red)', padding: '5px 10px', fontSize: 12 }}>Remove</button>
                      </div>
                    </div>
                  ) : (
                    <label className="btn btn-secondary" style={{ cursor: 'pointer', margin: 0, fontSize: 13 }} disabled={uploading}>
                      {uploading ? 'Uploading...' : '🖼️ Upload Header Banner'}
                      <input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'header_image_url')} disabled={uploading} />
                    </label>
                  )}
                </div>

                {/* Subject — always editable */}
                <div className="form-group" style={{ marginBottom: 14 }}>
                  <label className="form-label">Subject Line</label>
                  <input
                    value={activeEmail.subject || ''}
                    onChange={e => updateDraft('subject', e.target.value)}
                    placeholder="Email subject..."
                    style={{ fontWeight: 600, fontSize: 14 }}
                  />
                </div>

                {/* Email Body — always editable */}
                <div className="form-group" style={{ marginBottom: 16 }}>
                  <label className="form-label">Email Body</label>
                  <textarea
                    value={activeEmail.body || ''}
                    onChange={e => updateDraft('body', e.target.value)}
                    style={{ minHeight: 260, fontSize: 14, lineHeight: 1.7, resize: 'vertical' }}
                    placeholder="Email body (supports Markdown formatting)..."
                  />
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>Supports Markdown: **bold**, *italic*, ## headings, - bullet lists. Preview renders formatted HTML.</div>
                </div>

                {/* Sender Information + Signature Template */}
                <div style={{ marginBottom: 16, padding: 14, border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
                    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sender Information</div>
                    <select style={{ width: 180, margin: 0, padding: '4px 8px', fontSize: 12 }} value={activeEmail.signature_template_id || ''} onChange={e => {
                      const id = parseInt(e.target.value);
                      if (id) {
                        const sig = signatures.find(s => s.id === id);
                        if (sig) updateDraftFields({ signature_template_id: id, full_name: sig.full_name || '', designation: sig.designation || '', department: sig.department || '', company: sig.company || '', sender_email: sig.email || '', phone: sig.phone || '', website: sig.website || '', linkedin: sig.linkedin || '', address: sig.address || '', logo_url: sig.logo_url || '', digital_signature_url: sig.digital_signature_url || '', header_image_url: sig.header_banner_url || '', footer_banner_url: sig.footer_banner_url || '' });
                      } else updateDraft('signature_template_id', null);
                    }}>
                      <option value="">Load Signature Template</option>
                      {signatures.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 16px' }}>
                    {[
                      { label: 'Full Name', key: 'full_name' },
                      { label: 'Designation', key: 'designation' },
                      { label: 'Company', key: 'company' },
                      { label: 'Department', key: 'department' },
                      { label: 'Email', key: 'sender_email' },
                      { label: 'Phone', key: 'phone' },
                      { label: 'Website', key: 'website' },
                      { label: 'LinkedIn', key: 'linkedin' },
                    ].map(({ label, key }) => (
                      <div key={key}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>{label}</div>
                        <input style={{ padding: '5px 8px', fontSize: 12 }} value={(activeEmail as any)[key] || ''} onChange={e => updateDraft(key as keyof EmailRecord, e.target.value)} placeholder={label} />
                      </div>
                    ))}
                  </div>
                  {/* Company Logo */}
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>Company Logo</div>
                    {activeEmail.logo_url ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <img src={getImgSrc(activeEmail.logo_url)} alt="Logo" style={{ maxWidth: 70, maxHeight: 35, borderRadius: 3, objectFit: 'contain' }} />
                        <label className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: 11, cursor: 'pointer', margin: 0 }}>Replace<input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'logo_url')} /></label>
                        <button className="btn btn-ghost" onClick={() => updateDraft('logo_url', '')} style={{ color: 'var(--red)', padding: '4px 8px', fontSize: 11 }}>Clear</button>
                      </div>
                    ) : (
                      <label className="btn btn-secondary" style={{ cursor: 'pointer', margin: 0, padding: '5px 10px', fontSize: 12 }} disabled={uploading}>
                        {uploading ? 'Uploading...' : 'Upload Logo'}
                        <input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'logo_url')} disabled={uploading} />
                      </label>
                    )}
                  </div>
                </div>

                {/* Signature Image */}
                <div style={{ marginBottom: 16, padding: 14, border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Signature Image <span style={{ fontWeight: 400, textTransform: 'none', fontSize: 11 }}>(optional, appears below Best Regards)</span></div>
                  {activeEmail.digital_signature_url ? (
                    <div>
                      <img src={getImgSrc(activeEmail.digital_signature_url)} alt="Signature" style={{ maxWidth: 180, maxHeight: 80, borderRadius: 3, objectFit: 'contain', display: 'block', marginBottom: 8 }} />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <label className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: 12, cursor: 'pointer', margin: 0 }}>Replace<input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'digital_signature_url')} /></label>
                        <button className="btn btn-ghost" onClick={() => updateDraft('digital_signature_url', '')} style={{ color: 'var(--red)', padding: '5px 10px', fontSize: 12 }}>Remove</button>
                      </div>
                    </div>
                  ) : (
                    <label className="btn btn-secondary" style={{ cursor: 'pointer', margin: 0, fontSize: 13 }} disabled={uploading}>
                      {uploading ? 'Uploading...' : '🖋️ Upload Signature Image'}
                      <input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'digital_signature_url')} disabled={uploading} />
                    </label>
                  )}
                </div>

                {/* Footer Banner */}
                <div style={{ marginBottom: 20, padding: 14, border: '1px solid var(--border)', borderRadius: 8 }}>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Footer Banner <span style={{ fontWeight: 400, textTransform: 'none', fontSize: 11 }}>(optional)</span></div>
                  {activeEmail.footer_banner_url ? (
                    <div>
                      <img src={getImgSrc(activeEmail.footer_banner_url)} alt="Footer" style={{ maxWidth: '100%', maxHeight: 100, borderRadius: 6, objectFit: 'cover', display: 'block', marginBottom: 8 }} />
                      <div style={{ display: 'flex', gap: 8 }}>
                        <label className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: 12, cursor: 'pointer', margin: 0 }}>Replace<input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'footer_banner_url')} /></label>
                        <button className="btn btn-ghost" onClick={() => updateDraft('footer_banner_url', '')} style={{ color: 'var(--red)', padding: '5px 10px', fontSize: 12 }}>Remove</button>
                      </div>
                    </div>
                  ) : (
                    <label className="btn btn-secondary" style={{ cursor: 'pointer', margin: 0, fontSize: 13 }} disabled={uploading}>
                      {uploading ? 'Uploading...' : '🖼️ Upload Footer Banner'}
                      <input type="file" accept="image/*" style={{ display: 'none' }} onChange={e => handleFileUpload(e, 'footer_banner_url')} disabled={uploading} />
                    </label>
                  )}
                </div>

                {/* Action Buttons */}
                <div style={{ display: 'flex', gap: 12 }}>
                  {activeEmail.status !== 'sent' && (
                    <button className="btn btn-primary" onClick={() => sendEmail(activeEmail.id)} disabled={sendingId === activeEmail.id} style={{ flex: 1, padding: '11px 20px', fontSize: 14 }}>
                      {sendingId === activeEmail.id ? '⏳ Sending...' : '📨 Send via Gmail'}
                    </button>
                  )}
                  {activeEmail.status === 'sent' && (
                    <div style={{ flex: 1, padding: '11px 20px', background: 'rgba(34,197,94,0.08)', border: '1px solid rgba(34,197,94,0.2)', borderRadius: 8, fontSize: 14, color: 'var(--green)', textAlign: 'center' }}>
                      ✓ Email Sent — {fmtDate(activeEmail.sent_at)}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* Live Preview — always visible when email is selected */}
            {activeEmail && !generating && !generatingAgain && (
              <div className="card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                  <div className="card-title" style={{ margin: 0 }}>👁️ Live Email Preview</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Matches exactly what the recipient will receive</div>
                </div>
                <div style={{ background: '#f8f9fa', borderRadius: 8, padding: 16 }}>
                  <div style={{ maxWidth: 640, margin: '0 auto', background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8, boxShadow: '0 2px 16px rgba(0,0,0,0.06)', overflow: 'hidden' }}>
                    {/* Email client header bar decoration */}
                    <div style={{ background: '#f5f5f5', borderBottom: '1px solid #e8e8e8', padding: '10px 16px', display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#ff5f57' }} />
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#febc2e' }} />
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#28c840' }} />
                      <span style={{ fontSize: 12, color: '#888', marginLeft: 8 }}>Preview — Gmail</span>
                    </div>
                    <div style={{ padding: '24px 28px', maxHeight: 680, overflowY: 'auto' }}>
                      {activeEmail.html_body ? (
                        <div dangerouslySetInnerHTML={{ __html: activeEmail.html_body }} />
                      ) : (
                        <div style={{ color: '#aaa', fontStyle: 'italic', textAlign: 'center', padding: '40px 0', fontSize: 14 }}>
                          ✍️ Start editing to see the preview update automatically
                        </div>
                      )}
                    </div>
                  </div>
                </div>
                <div style={{ marginTop: 12, fontSize: 11, color: 'var(--text-muted)', textAlign: 'center' }}>
                  Preview updates automatically · Markdown is rendered · Header, footer, and signature are included
                </div>
              </div>
            )}

          </div>
        </div>
      )}

      {tab === 'campaigns' && (
        <div className="card">
          <div className="card-title" style={{ marginBottom: 16 }}>All Campaigns</div>
          {campaigns.length === 0 ? (
            <div className="empty-state">No campaigns yet. Generate outreach to create campaigns automatically.</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>#</th><th>Campaign Name</th><th>Status</th><th>Emails Sent</th><th>Replies</th><th>Created</th></tr></thead>
                <tbody>
                  {campaigns.map(c => (
                    <tr key={c.id}>
                      <td style={{ color: 'var(--text-muted)' }}>#{c.id}</td>
                      <td style={{ fontWeight: 600 }}>{c.name}</td>
                      <td><StatusBadge status={c.status} /></td>
                      <td>{c.emails_sent || 0}</td>
                      <td>{c.replies || 0}</td>
                      <td style={{ color: 'var(--text-muted)', fontSize: 13 }}>{fmtDate(c.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'templates' && (
        <div>
          {/* Sub-tab bar */}
          <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
            <button className={`btn ${templateSubTab === 'message' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setTemplateSubTab('message')}>📝 Message Templates</button>
            <button className={`btn ${templateSubTab === 'branding' ? 'btn-primary' : 'btn-ghost'}`} onClick={() => setTemplateSubTab('branding')}>🎨 Signature Branding</button>
          </div>

          {/* ── MESSAGE TEMPLATES ── */}
          {templateSubTab === 'message' && (
            <div>
              {/* Preview Modal */}
              {previewTemplate && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }} onClick={() => setPreviewTemplate(null)}>
                  <div style={{ background: 'var(--bg-card)', borderRadius: 12, padding: 32, maxWidth: 680, width: '100%', maxHeight: '80vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
                      <div>
                        <div style={{ fontWeight: 700, fontSize: 18 }}>{previewTemplate.name}</div>
                        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>{previewTemplate.category} {previewTemplate.is_default ? '· Built-in (read-only)' : '· Custom'}</div>
                      </div>
                      <button className="btn btn-ghost" onClick={() => setPreviewTemplate(null)}>✕ Close</button>
                    </div>
                    <div style={{ marginBottom: 12, padding: '10px 14px', background: 'var(--bg-card-hover)', borderRadius: 6 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 4 }}>SUBJECT</div>
                      <div style={{ fontWeight: 600 }}>{previewTemplate.subject}</div>
                    </div>
                    <div style={{ padding: '14px 16px', background: 'var(--bg-card-hover)', borderRadius: 6 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>BODY</div>
                      <pre style={{ fontFamily: 'inherit', whiteSpace: 'pre-wrap', fontSize: 14, lineHeight: 1.7, margin: 0 }}>{previewTemplate.body}</pre>
                    </div>
                    <div style={{ marginTop: 16, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      {['{{company_name}}','{{contact_name}}','{{designation}}','{{industry}}','{{city}}','{{state}}','{{buying_signal}}','{{sender_name}}'].map(p => (
                        <span key={p} style={{ background: 'rgba(139,92,246,0.12)', border: '1px solid rgba(139,92,246,0.3)', borderRadius: 4, padding: '2px 8px', fontSize: 11, color: 'var(--accent-glow)', fontFamily: 'monospace' }}>{p}</span>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {/* Edit/Create Modal */}
              {editingTemplate && (
                <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)', zIndex: 1000, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }} onClick={() => setEditingTemplate(null)}>
                  <div style={{ background: 'var(--bg-card)', borderRadius: 12, padding: 32, maxWidth: 720, width: '100%', maxHeight: '85vh', overflowY: 'auto' }} onClick={e => e.stopPropagation()}>
                    <div style={{ fontWeight: 700, fontSize: 18, marginBottom: 20 }}>{editingTemplate.id ? 'Edit Template' : 'Create Template'}</div>
                    <div className="grid-2" style={{ gap: 16, marginBottom: 16 }}>
                      <div className="form-group">
                        <label className="form-label">Template Name *</label>
                        <input className="input" value={editingTemplate.name || ''} onChange={e => setEditingTemplate({...editingTemplate, name: e.target.value})} placeholder="e.g. Healthcare Cold Outreach" />
                      </div>
                      <div className="form-group">
                        <label className="form-label">Category</label>
                        <select className="input" value={editingTemplate.category || 'Custom'} onChange={e => setEditingTemplate({...editingTemplate, category: e.target.value})}>
                          {['Prospecting','Introduction','Scheduling','Follow-up','Demo','Post-Meeting','Custom'].map(c => <option key={c}>{c}</option>)}
                        </select>
                      </div>
                    </div>
                    <div className="form-group" style={{ marginBottom: 16 }}>
                      <label className="form-label">Subject Line *</label>
                      <input className="input" style={{ width: '100%' }} value={editingTemplate.subject || ''} onChange={e => setEditingTemplate({...editingTemplate, subject: e.target.value})} placeholder="e.g. AI Solutions for {{company_name}}" />
                    </div>
                    <div className="form-group" style={{ marginBottom: 12 }}>
                      <label className="form-label">Email Body</label>
                      <textarea
                        className="input"
                        value={editingTemplate.body || ''}
                        onChange={e => setEditingTemplate({...editingTemplate, body: e.target.value})}
                        style={{ width: '100%', minHeight: 280, fontFamily: 'inherit', fontSize: 14, lineHeight: 1.7, resize: 'vertical' }}
                        placeholder={`Dear {{contact_name}},\n\nYour personalized message here...`}
                      />
                    </div>
                    <div style={{ marginBottom: 16 }}>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>Click to insert placeholder:</div>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {['{{company_name}}','{{contact_name}}','{{designation}}','{{industry}}','{{city}}','{{state}}','{{country}}','{{company_summary}}','{{buying_signal}}','{{sender_name}}'].map(p => (
                          <button key={p} className="btn btn-ghost" style={{ padding: '3px 8px', fontSize: 11, fontFamily: 'monospace' }}
                            onClick={() => setEditingTemplate({...editingTemplate, body: (editingTemplate.body || '') + p})}>
                            {p}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 10 }}>
                      <button className="btn btn-primary" onClick={saveOutreachTemplate}>💾 Save Template</button>
                      <button className="btn btn-ghost" onClick={() => setEditingTemplate(null)}>Cancel</button>
                    </div>
                  </div>
                </div>
              )}

              {/* Header bar */}
              <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap', alignItems: 'center' }}>
                <input
                  className="input"
                  placeholder="Search templates..."
                  value={templateSearch}
                  onChange={e => setTemplateSearch(e.target.value)}
                  style={{ maxWidth: 220, flex: 1 }}
                />
                <select className="input" value={templateCategory} onChange={e => setTemplateCategory(e.target.value)} style={{ maxWidth: 180 }}>
                  <option value="">All Categories</option>
                  {['Prospecting','Introduction','Scheduling','Follow-up','Demo','Post-Meeting','Custom'].map(c => <option key={c}>{c}</option>)}
                </select>
                <button className="btn btn-primary" style={{ marginLeft: 'auto' }} onClick={() => setEditingTemplate({ name: '', subject: '', body: '', category: 'Custom' })}>+ New Template</button>
              </div>

              {/* Template grid */}
              <div className="grid-2">
                {outreachTemplates
                  .filter(t => (!templateSearch || t.name.toLowerCase().includes(templateSearch.toLowerCase()) || t.subject?.toLowerCase().includes(templateSearch.toLowerCase()))
                            && (!templateCategory || t.category === templateCategory))
                  .map(t => (
                  <div key={t.id} style={{ padding: 18, border: `1px solid ${t.is_set_as_default ? 'var(--accent-glow)' : 'var(--border)'}`, borderRadius: 10, background: 'var(--bg-card-hover)', display: 'flex', flexDirection: 'column', gap: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
                      <div style={{ flex: 1 }}>
                        <div style={{ fontWeight: 700, fontSize: 15, display: 'flex', alignItems: 'center', gap: 6 }}>
                          {t.is_set_as_default && <span style={{ color: 'var(--amber)', fontSize: 13 }}>★</span>}
                          {t.name}
                        </div>
                        <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
                          <span style={{ background: 'rgba(99,102,241,0.15)', color: 'var(--accent-glow)', borderRadius: 4, padding: '2px 7px', fontSize: 11 }}>{t.category}</span>
                          {t.is_default ? (
                            <span style={{ background: 'rgba(245,158,11,0.12)', color: 'var(--amber)', borderRadius: 4, padding: '2px 7px', fontSize: 11 }}>Built-in</span>
                          ) : (
                            <span style={{ background: 'rgba(34,197,94,0.1)', color: 'var(--green)', borderRadius: 4, padding: '2px 7px', fontSize: 11 }}>Custom</span>
                          )}
                        </div>
                      </div>
                    </div>
                    <div style={{ fontSize: 13, color: 'var(--text-secondary)', fontStyle: 'italic' }}>Subject: {t.subject?.slice(0, 70)}{(t.subject?.length > 70) ? '…' : ''}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', maxHeight: 48, overflow: 'hidden', maskImage: 'linear-gradient(to bottom, black 60%, transparent)' }}>{t.body?.slice(0, 120)}</div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
                      <button className="btn btn-ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => setPreviewTemplate(t)}>👁 Preview</button>
                      <button className="btn btn-ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => duplicateTemplate(t.id)}>⧉ Duplicate</button>
                      <button className={`btn btn-ghost`} style={{ padding: '4px 10px', fontSize: 12, color: t.is_set_as_default ? 'var(--amber)' : undefined }} onClick={() => setAsDefaultTemplate(t.id)}>
                        {t.is_set_as_default ? '★ Default' : '☆ Set Default'}
                      </button>
                      {!t.is_default && (
                        <>
                          <button className="btn btn-ghost" style={{ padding: '4px 10px', fontSize: 12 }} onClick={() => setEditingTemplate({...t})}>✏ Edit</button>
                          <button className="btn btn-ghost" style={{ padding: '4px 10px', fontSize: 12, color: 'var(--red)' }} onClick={() => deleteOutreachTemplate(t.id)}>🗑 Delete</button>
                        </>
                      )}
                    </div>
                  </div>
                ))}
                {outreachTemplates.length === 0 && (
                  <div className="empty-state" style={{ gridColumn: '1 / -1' }}>No templates yet. Click "+ New Template" or wait for defaults to load.</div>
                )}
              </div>
            </div>
          )}

          {/* ── SIGNATURE BRANDING ── */}
          {templateSubTab === 'branding' && (
            <div className="card">
              <div className="card-title" style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span>Signature Branding</span>
                {!editingSig && <button className="btn btn-primary" onClick={() => setEditingSig({ name: 'New Template' })}>+ New Template</button>}
              </div>
          
          {editingSig ? (
            <div style={{ background: 'var(--bg-card-hover)', padding: 20, borderRadius: 8 }}>
                <h3 style={{ marginTop: 0, marginBottom: 20 }}>{editingSig.id ? 'Edit Template' : 'Create Template'}</h3>
                <div className="grid-2" style={{ gap: 20 }}>
                    <div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Template Name</label>
                            <input value={editingSig.name || ''} onChange={e => setEditingSig({...editingSig, name: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Full Name</label>
                            <input value={editingSig.full_name || ''} onChange={e => setEditingSig({...editingSig, full_name: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Designation</label>
                            <input value={editingSig.designation || ''} onChange={e => setEditingSig({...editingSig, designation: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Department (Optional)</label>
                            <input value={editingSig.department || ''} onChange={e => setEditingSig({...editingSig, department: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Company Name</label>
                            <input value={editingSig.company || ''} onChange={e => setEditingSig({...editingSig, company: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Email</label>
                            <input value={editingSig.email || ''} onChange={e => setEditingSig({...editingSig, email: e.target.value})} />
                        </div>
                    </div>
                    <div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Phone</label>
                            <input value={editingSig.phone || ''} onChange={e => setEditingSig({...editingSig, phone: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Website</label>
                            <input value={editingSig.website || ''} onChange={e => setEditingSig({...editingSig, website: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">LinkedIn URL</label>
                            <input value={editingSig.linkedin || ''} onChange={e => setEditingSig({...editingSig, linkedin: e.target.value})} />
                        </div>
                        <div className="form-group" style={{ marginBottom: 15 }}>
                            <label className="form-label">Office Address (Optional)</label>
                            <textarea value={editingSig.address || ''} onChange={e => setEditingSig({...editingSig, address: e.target.value})} style={{ minHeight: 60 }} />
                        </div>
                        
                        <div style={{ marginTop: 20 }}>
                            <h4 style={{ marginBottom: 10, fontSize: 14 }}>Branding Images</h4>
                            {['header_banner_url', 'logo_url', 'digital_signature_url', 'footer_banner_url'].map(field => (
                                <div key={field} style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 10 }}>
                                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10 }}>
                                        <div style={{ fontSize: 13, fontWeight: 600, width: 150 }}>{field.replace(/_url/g, '').replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}</div>
                                        {editingSig[field as keyof SignatureTemplate] ? (
                                            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                                <img src={getImgSrc(editingSig[field as keyof SignatureTemplate] as string)} style={{ height: 30, borderRadius: 4, objectFit: 'contain' }} />
                                                <button className="btn btn-ghost" onClick={() => setEditingSig({...editingSig, [field]: ''})} style={{ padding: '4px 8px', fontSize: 12, color: 'var(--red)' }}>Clear</button>
                                            </div>
                                        ) : (
                                            <div>
                                                <input type="file" accept="image/*" style={{ fontSize: 12 }} onChange={async (e) => {
                                                    const file = e.target.files?.[0];
                                                    if (!file) return;
                                                    const fd = new FormData(); fd.append('file', file);
                                                    const res = await fetch(`${API}/outreach/upload`, { method: 'POST', body: fd });
                                                    const data = await res.json();
                                                    if (data.url) setEditingSig({...editingSig, [field]: data.url});
                                                }} />
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
                <div style={{ marginTop: 20, display: 'flex', gap: 10 }}>
                    <button className="btn btn-primary" onClick={async () => {
                        const m = editingSig.id ? 'PUT' : 'POST';
                        const u = editingSig.id ? `/outreach/signatures/${editingSig.id}` : `/outreach/signatures`;
                        // Optional: a helper function instead of raw fetch, but postJSON handles this well if it supports PUT. We will use fetch just to be safe.
                        await fetch(`${API}${u}`, { method: m, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(editingSig) });
                        setEditingSig(null);
                        loadSignatures();
                    }}>Save Template</button>
                    <button className="btn btn-ghost" onClick={() => setEditingSig(null)}>Cancel</button>
                </div>
            </div>
          ) : (
            <div className="grid-2">
                {signatures.map(s => (
                    <div key={s.id} style={{ padding: 16, border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-card-hover)' }}>
                        <div style={{ fontWeight: 600, fontSize: 16, marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
                            {s.name}
                            <button className="btn btn-ghost" onClick={() => setEditingSig(s)} style={{ padding: '4px 8px' }}>Edit</button>
                        </div>
                        <div style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{s.full_name} — {s.designation}</div>
                        <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>{s.company}</div>
                        <div style={{ marginTop: 10, display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                            {s.header_banner_url && <span className="badge">Header</span>}
                            {s.digital_signature_url && <span className="badge">Signature</span>}
                            {s.footer_banner_url && <span className="badge">Footer</span>}
                        </div>
                    </div>
                ))}
            </div>
          )}
            </div>
          )}
        </div>
      )}
    </>
  );
}

