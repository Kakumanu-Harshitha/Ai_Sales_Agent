import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';

function ProspectingJobHistory() {
  const [open, setOpen] = useState(false);
  const [jobs, setJobs] = useState<any[]>([]);

  const loadJobs = async () => {
    const data = await fetchJSON<any[]>('/orchestration/jobs?limit=10');
    if (data) setJobs(data);
  };

  useEffect(() => {
    if (open) loadJobs();
  }, [open]);

  if (!open) return <button className="btn btn-secondary" style={{ marginBottom: 20 }} onClick={() => setOpen(true)}>View Job History</button>;

  return (
    <div className="card" style={{ marginBottom: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div className="card-title">Past Prospecting Jobs</div>
        <button className="btn btn-secondary" onClick={() => setOpen(false)}>Close</button>
      </div>
      {jobs.length === 0 ? (
        <div className="empty-state">No jobs found in database.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {jobs.map(job => (
            <div key={job.id} style={{ border: '1px solid var(--border)', padding: 12, borderRadius: 8, background: 'var(--bg)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <strong style={{ fontSize: 14 }}>Job #{job.id}</strong>
                <span className={`badge badge-${job.status === 'Running' ? 'blue' : job.status === 'Error' ? 'amber' : 'green'}`}>
                  {job.status}
                </span>
              </div>
              <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
                Started: {new Date(job.start_time).toLocaleString()}
                <br />
                Discovered: {job.companies_discovered || 0} | Qualified: {job.contacts_verified || 0} | Saved: {job.leads_found || 0}
              </div>
              {job.logs && job.logs.length > 0 && (
                <details style={{ marginTop: 8 }}>
                  <summary style={{ fontSize: 12, color: 'var(--text-primary)', cursor: 'pointer' }}>View Logs</summary>
                  <div style={{ marginTop: 8, background: 'var(--bg-card)', padding: 8, borderRadius: 4, maxHeight: 150, overflowY: 'auto', fontFamily: 'monospace', fontSize: 11 }}>
                    {job.logs.map((log: string, i: number) => (
                      <div key={i}>{log}</div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const ROLE_CATEGORIES = {
  "Executive Leadership": ["CEO", "COO", "CFO", "CIO", "CTO", "Chief Medical Officer (CMO)", "Chief Nursing Officer (CNO)", "VP of Operations", "Director of IT", "Hospital Administrator"],
  "Clinical Leadership": ["Medical Director", "Clinical Director", "Department Head", "Practice Manager"],
  "Doctors / Specialists": ["General Physician", "Cardiologist", "Neurologist", "Pulmonologist", "Oncologist", "Orthopedic Surgeon", "Gastroenterologist", "Nephrologist", "Endocrinologist", "Dermatologist", "Pediatrician", "Gynecologist", "Urologist", "ENT Specialist", "Ophthalmologist", "Psychiatrist", "Anesthesiologist", "Emergency Medicine Physician", "Radiologist", "Pathologist"],
  "Nursing & Clinical Operations": ["Nursing Director", "Head Nurse", "ICU Manager", "Laboratory Director", "Pharmacy Director"],
  "Healthcare IT & Digital Transformation": ["Health Informatics Manager", "EMR/EHR Administrator", "Digital Transformation Lead", "AI Program Manager", "Telemedicine Director", "Biomedical Engineer"],
  "Procurement & Operations": ["Procurement Manager", "Purchasing Manager", "Supply Chain Manager", "Operations Manager"]
};
const ALL_ORG_TYPES = ["Hospital & Health Care", "Medical Practice", "Healthcare Technology", "Hospital", "Clinic", "Diagnostic Chain"];

export default function ProspectingPage() {
  const [form, setForm] = useState({
    industries: ['Hospital & Health Care'],
    regions: 'United States',
    keywords: 'AI diagnostics, EMR, telemedicine',
    target_roles: ['CTO', 'CIO', 'Director of IT'],
    company_size_min: '50',
    company_size_max: '5000',
    technologies: 'AWS, Python',
    max_results: 15
  });

  const [templates, setTemplates] = useState<any[]>([]);

  const loadTemplates = async () => {
    const d = await fetchJSON<any[]>('/orchestration/templates');
    if (d) setTemplates(d);
  };

  useEffect(() => { loadTemplates(); }, []);

  const [running, setRunning] = useState(false);
  const [log, setLog] = useState<string[]>([]);
  const [apiStatus, setApiStatus] = useState<string>('');
  const logRef = useRef<HTMLDivElement>(null);

  const [liveCompanies, setLiveCompanies] = useState<any[]>([]);
  const [roleModalOpen, setRoleModalOpen] = useState(false);
  const [roleSearch, setRoleSearch] = useState('');
  const [expandedCategories, setExpandedCategories] = useState<Record<string, boolean>>({});
  const toggleCategory = (cat: string) => setExpandedCategories(p => ({...p, [cat]: !p[cat]}));

  const appendLog = (msg: string) =>
    setLog(prev => [...prev, `[${new Date().toLocaleTimeString()}] ${msg}`]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const toggleRole = (role: string) => {
    setForm(f => ({
      ...f,
      target_roles: f.target_roles.includes(role) 
        ? f.target_roles.filter(r => r !== role) 
        : [...f.target_roles, role]
    }));
  };

  const toggleIndustry = (ind: string) => {
    setForm(f => ({
      ...f,
      industries: f.industries.includes(ind) 
        ? f.industries.filter(i => i !== ind) 
        : [...f.industries, ind]
    }));
  };

  const runDiscover = async () => {
    setRunning(true);
    setLog([]);
    setLiveCompanies([]);
    setApiStatus('');

    appendLog('Initializing Prospecting Agent Background Job...');
    
    const keywordsList = form.keywords ? form.keywords.split(',').map(k => k.trim()).filter(Boolean) : [];
    const regionsList = form.regions ? form.regions.split(',').map(r => r.trim()).filter(Boolean) : [];
    const techList = form.technologies ? form.technologies.split(',').map(t => t.trim()).filter(Boolean) : [];
    
    const payload = {
      industries: form.industries,
      regions: regionsList,
      keywords: keywordsList,
      target_roles: form.target_roles,
      company_size_min: parseInt(form.company_size_min) || undefined,
      company_size_max: parseInt(form.company_size_max) || undefined,
      technologies: techList,
      max_results: form.max_results
    };

    appendLog(`Payload: ${JSON.stringify(payload)}`);

    const res = await postJSON<{job_id: number, status: string, message: string}>('/prospecting/search', payload);

    if (!res || !res.job_id) {
      appendLog('⚠ Network error — could not start job. Is the server running?');
      setApiStatus('error');
      setRunning(false);
      return;
    }

    appendLog(`Job #${res.job_id} started. Polling status...`);
    
    const poll = setInterval(async () => {
      const statusRes = await fetchJSON<any>(`/prospecting/jobs/${res.job_id}`);
      if (!statusRes) return;
      
      setLiveCompanies(statusRes.discovered_companies || []);

      if (statusRes.status === 'completed') {
        clearInterval(poll);
        appendLog(`✓ Job complete!`);
        appendLog(`Companies discovered: ${statusRes.total_companies_discovered}`);
        appendLog(`Leads qualified: ${statusRes.total_leads_qualified}`);
        appendLog(`Leads automatically saved to CRM: ${statusRes.total_leads_persisted}`);
        appendLog(`Navigate to the CRM or Outreach tabs to view your new prospects.`);
        setRunning(false);
      } else if (statusRes.status === 'failed') {
        clearInterval(poll);
        appendLog(`✗ Job failed: ${statusRes.error_message}`);
        setRunning(false);
      } else {
        appendLog(`[Job: ${statusRes.status}] Discovered: ${statusRes.total_companies_discovered} | Qualified: ${statusRes.total_leads_qualified} | Persisted: ${statusRes.total_leads_persisted}`);
      }
    }, 4000);
  };

  return (
    <>
      <div className="page-header">
        <div>
          <div className="page-title">🔍 Prospecting Agent</div>
          <div className="page-subtitle">Build your Ideal Customer Profile (ICP) and let AI find qualified leads across Apollo, NPI, and the Web.</div>
        </div>
      </div>

      <ProspectingJobHistory />


      <div className="grid-1-2">
        {/* LEFT PANEL: Job Templates */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card">
            <h3 className="card-title">Job Templates</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 16 }}>Select a template to instantly populate the discovery form.</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {templates.length === 0 ? (
                <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>No templates found in database.</div>
              ) : templates.map(t => (
                <button
                  key={t.id}
                  className="btn btn-ghost"
                  style={{ justifyContent: 'flex-start', textAlign: 'left' }}
                  onClick={() => {
                    setForm({
                      ...form,
                      industries: t.industries ? t.industries.split(',').map((x: string) => x.trim()) : [],
                      target_roles: t.target_roles ? t.target_roles.split(',').map((x: string) => x.trim()) : [],
                      regions: t.regions || '',
                      company_size_min: t.company_size_min || '50',
                      company_size_max: t.company_size_max || '5000',
                      keywords: t.keywords || '',
                      technologies: t.technologies || '',
                      max_results: t.max_results || 15
                    });
                  }}
                >
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{t.name}</div>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{t.industries?.substring(0, 30)}...</div>
                  </div>
                </button>
              ))}
            </div>

            <button
              className="btn btn-secondary"
              style={{ width: '100%', marginTop: 24, padding: '10px 20px', borderRadius: '8px', fontSize: '14px', fontWeight: 600, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', cursor: 'pointer' }}
              onClick={async () => {
                const name = prompt("Enter a name for this template:");
                if (name) {
                  await postJSON('/orchestration/templates', {
                    name,
                    industries: form.industries.join(', '),
                    target_roles: form.target_roles.join(', '),
                    regions: form.regions,
                    company_size_min: form.company_size_min,
                    company_size_max: form.company_size_max,
                    keywords: form.keywords,
                    technologies: form.technologies,
                    max_results: form.max_results
                  });
                  loadTemplates();
                }
              }}
            >
              + Save Current as Template
            </button>
          </div>
        </div>

        {/* RIGHT PANEL: ICP Form */}
        <div className="card" style={{ marginBottom: 24 }}>
          <div className="card-title" style={{ marginBottom: 16 }}>Ideal Customer Profile (ICP) Configuration</div>
        
        <div className="form-row form-row-2">
          <div className="form-group">
            <label className="form-label">Geography / Regions (comma-separated)</label>
            <input placeholder="e.g. California, United States, Mumbai" value={form.regions} onChange={e => setForm(f => ({ ...f, regions: e.target.value }))} />
          </div>
          <div className="form-group">
            <label className="form-label">Company Size</label>
            <div style={{ display: 'flex', gap: 10 }}>
              <input type="number" placeholder="Min" value={form.company_size_min} onChange={e => setForm(f => ({ ...f, company_size_min: e.target.value }))} />
              <span style={{ display: 'flex', alignItems: 'center' }}>-</span>
              <input type="number" placeholder="Max" value={form.company_size_max} onChange={e => setForm(f => ({ ...f, company_size_max: e.target.value }))} />
            </div>
          </div>
        </div>

        <div className="form-group" style={{ marginBottom: 20 }}>
          <label className="form-label">Target Organization Types</label>
          <div className="checkbox-group">
            {ALL_ORG_TYPES.map(ind => (
              <label key={ind} className="checkbox-label">
                <input type="checkbox" style={{ width: 'auto' }} checked={form.industries.includes(ind)} onChange={() => toggleIndustry(ind)} />
                <span>{ind}</span>
              </label>
            ))}
          </div>
        </div>

        <div className="form-group" style={{ marginBottom: 20 }}>
          <label className="form-label">Target Decision-Maker Roles</label>
          <button 
            type="button" 
            className="btn btn-secondary" 
            onClick={() => setRoleModalOpen(true)}
            style={{ marginBottom: 10, display: 'block' }}
          >
            Select Decision Makers
          </button>
          
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {form.target_roles.slice(0, 5).map(role => (
              <div key={role} style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '4px 10px', backgroundColor: 'var(--bg-card-hover)',
                borderRadius: 16, fontSize: 13, border: '1px solid var(--border)'
              }}>
                {role}
                <button onClick={() => toggleRole(role)} style={{ 
                  background: 'none', border: 'none', color: 'var(--text-secondary)', 
                  cursor: 'pointer', padding: 0, display: 'flex', alignItems: 'center'
                }}>✕</button>
              </div>
            ))}
            {form.target_roles.length > 5 && (
              <button 
                onClick={() => setRoleModalOpen(true)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  padding: '4px 10px', backgroundColor: 'var(--bg-card-hover)',
                  borderRadius: 16, fontSize: 13, border: '1px solid var(--border)',
                  color: 'var(--text-secondary)', cursor: 'pointer'
                }}
              >
                [+{form.target_roles.length - 5} More]
              </button>
            )}
          </div>
        </div>

        {roleModalOpen && (
          <div style={{
            position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.75)', 
            display: 'flex',
            alignItems: 'center', justifyContent: 'center', zIndex: 9999
          }} onClick={() => setRoleModalOpen(false)}>
            <div style={{
              backgroundColor: 'var(--bg-card)', width: 600, maxWidth: '90%',
              maxHeight: '80vh', display: 'flex', flexDirection: 'column',
              borderRadius: 8, overflow: 'hidden', border: '1px solid var(--border)'
            }} onClick={e => e.stopPropagation()}>
              <div style={{ padding: 20, borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <h3 style={{ margin: 0, fontSize: 18, color: 'var(--text-primary)' }}>Select Target Roles</h3>
                <button onClick={() => setRoleModalOpen(false)} style={{ background: 'none', border: 'none', fontSize: 20, cursor: 'pointer', color: 'var(--text-secondary)' }}>✕</button>
              </div>
              
              <div style={{ padding: 20, borderBottom: '1px solid var(--border)' }}>
                <input 
                  type="text" 
                  className="input" 
                  placeholder="Search all roles (e.g., Cardiologist, Director)..." 
                  value={roleSearch}
                  onChange={e => setRoleSearch(e.target.value)}
                  style={{ width: '100%' }}
                  autoFocus
                />
              </div>

              <div style={{ padding: 20, overflowY: 'auto', flex: 1 }}>
                {Object.entries(ROLE_CATEGORIES).map(([category, roles]) => {
                  const filteredRoles = roles.filter(r => r.toLowerCase().includes(roleSearch.toLowerCase()));
                  if (filteredRoles.length === 0) return null;
                  
                  const isExpanded = roleSearch ? true : expandedCategories[category];

                  return (
                    <div key={category} style={{ marginBottom: 15 }}>
                      <div 
                        onClick={() => toggleCategory(category)}
                        style={{ 
                          fontSize: 14, fontWeight: 600, color: 'var(--text-primary)', 
                          padding: '8px 0', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 8,
                          userSelect: 'none'
                        }}
                      >
                        <span style={{ transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)', transition: 'transform 0.2s', display: 'inline-block', fontSize: 10 }}>▶</span>
                        {category}
                        <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontWeight: 'normal' }}>({filteredRoles.length})</span>
                      </div>
                      
                      {isExpanded && (
                        <div style={{ paddingLeft: 16, marginTop: 8, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 10 }}>
                          {filteredRoles.map(role => (
                            <label key={role} style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 14 }}>
                              <input 
                                type="checkbox" 
                                checked={form.target_roles.includes(role)} 
                                onChange={() => toggleRole(role)}
                                style={{ width: 'auto', margin: 0 }}
                              />
                              <span style={{ color: form.target_roles.includes(role) ? 'var(--text-primary)' : 'var(--text-secondary)' }}>{role}</span>
                            </label>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>

              <div style={{ padding: 20, borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
                <button type="button" className="btn btn-ghost" onClick={() => setRoleModalOpen(false)}>Cancel</button>
                <button type="button" className="btn btn-primary" onClick={() => setRoleModalOpen(false)}>Apply Selection ({form.target_roles.length})</button>
              </div>
            </div>
          </div>
        )}

        <div className="form-row form-row-2">
          <div className="form-group">
            <label className="form-label">Pain Points & Keywords (comma-separated)</label>
            <input placeholder="e.g. AI diagnostics, EMR, telemedicine" value={form.keywords} onChange={e => setForm(f => ({ ...f, keywords: e.target.value }))} />
          </div>
          <div className="form-group">
            <label className="form-label">Technologies Used (comma-separated)</label>
            <input placeholder="e.g. AWS, Python, Epic Systems" value={form.technologies} onChange={e => setForm(f => ({ ...f, technologies: e.target.value }))} />
          </div>
        </div>

        <div className="form-row form-row-2" style={{ alignItems: 'flex-end', marginTop: 12 }}>
          <div className="form-group">
            <label className="form-label">Max Results per Provider</label>
            <input type="number" min="1" max="100" value={form.max_results} onChange={e => setForm(f => ({ ...f, max_results: parseInt(e.target.value) || 15 }))} />
          </div>
          <button className="btn btn-primary" onClick={runDiscover} disabled={running} style={{ height: 44, justifyContent: 'center' }}>
            {running
              ? <><div className="spinner" style={{ width: 16, height: 16, margin: 0 }} />Discovering Leads...</>
              : '🔍 Start AI Lead Discovery Job'}
          </button>
        </div>
      </div>
      </div>

      {(log.length > 0 || liveCompanies.length > 0) && (
        <div className="grid-1-2" style={{ marginBottom: 24, alignItems: 'flex-start' }}>
          {/* Live Progress Cards */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="card" style={{ padding: 16 }}>
              <h3 className="card-title" style={{ marginBottom: 12 }}>Live Discoveries ({liveCompanies.length})</h3>
              {liveCompanies.length === 0 ? (
                <div className="empty-state" style={{ padding: 20 }}>Waiting for Agent to discover companies...</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                  {liveCompanies.map((c, i) => (
                    <details key={i} style={{ border: '1px solid var(--border)', borderRadius: 8, padding: '10px 14px', background: 'var(--bg)' }}>
                      <summary style={{ cursor: 'pointer', fontWeight: 600, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span style={{ fontSize: 14 }}>{c.name}</span>
                        <span className={`badge badge-${c.status === 'Discovered' ? 'blue' : c.status === 'Qualified Lead' ? 'green' : 'amber'}`}>
                          {c.status}
                        </span>
                      </summary>
                      <div style={{ marginTop: 12, display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: 13, color: 'var(--text-secondary)' }}>
                        <div><strong>Type:</strong> {c.org_type}</div>
                        <div><strong>Industry:</strong> {c.industry}</div>
                        <div><strong>Location:</strong> {c.city}, {c.state}, {c.country}</div>
                        <div><strong>Employees:</strong> {c.employee_count}</div>
                        <div style={{ gridColumn: 'span 2' }}>
                          <strong>Website:</strong> {c.website && c.website !== 'Unknown' ? <a href={c.website.startsWith('http') ? c.website : `https://${c.website}`} target="_blank" rel="noreferrer" style={{ color: 'var(--primary)' }}>{c.website}</a> : 'N/A'}
                        </div>
                        <div style={{ gridColumn: 'span 2' }}><strong>Source:</strong> {c.source}</div>
                      </div>
                    </details>
                  ))}
                </div>
              )}
            </div>
          </div>
          
          {/* Execution Log */}
          <div className="card" style={{ flex: 1 }}>
            <div className="card-title" style={{ marginBottom: 12 }}>Agent Execution Log</div>
            <div className="progress-log" ref={logRef}>
              {log.map((l, i) => <div key={i}>{l}</div>)}
            </div>
          </div>
        </div>
      )}

      {!running && apiStatus === 'error' && (
        <div className="card" style={{ borderColor: 'rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.05)' }}>
          <div style={{ display: 'flex', gap: 14, alignItems: 'flex-start' }}>
            <span style={{ fontSize: 28 }}>⚠️</span>
            <div>
              <div style={{ fontWeight: 700, marginBottom: 8, color: 'var(--red)', fontSize: 16 }}>Failed to start job</div>
              <div style={{ fontSize: 14, color: 'var(--text-secondary)', lineHeight: 1.6 }}>Could not connect to the backend server. Please make sure the API is running on localhost:8000.</div>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

