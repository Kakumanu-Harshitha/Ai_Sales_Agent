import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';


export default function AgentStatusPanel() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);

  useEffect(() => {
    const load = async () => {
      const d = await fetchJSON<{ agents: AgentStatus[] }>('/agents/status');
      if (d) setAgents(d.agents);
    };
    load();
    const interval = setInterval(load, 15000);
    return () => clearInterval(interval);
  }, []);

  if (agents.length === 0) return null;

  return (
    <div className="agent-status-mini">
      <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Agent Status</div>
      {agents.map(a => (
        <div key={a.key} style={{ padding: '6px 0', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span className={`agent-dot ${a.status}`} />
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{a.name}</span>
        </div>
      ))}
    </div>
  );
}

