import React, { useState, useEffect } from 'react';
import { AgentStatus } from '../../types';
import { fetchJSON } from '../../utils/api';

export default function AgentStatusSidebar() {
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
      <div className="agent-status-mini-title">Agent Status</div>
      {agents.map(a => {
        const statusKey = a.status?.toLowerCase();
        return (
          <div
            key={a.key}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '5px 0',
            }}
          >
            <span
              className={`agent-dot ${statusKey || 'idle'}`}
            />
            <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.55)', flex: 1 }}>
              {a.name}
            </span>
            <span style={{
              fontSize: 10,
              fontWeight: 600,
              color: statusKey === 'running'
                ? 'var(--gold)'
                : statusKey === 'completed'
                  ? '#4ade80'
                  : 'rgba(255,255,255,0.25)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}>
              {a.status}
            </span>
          </div>
        );
      })}
    </div>
  );
}
