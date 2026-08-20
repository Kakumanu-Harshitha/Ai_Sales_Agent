import React, { useState, useEffect } from 'react';
import { fetchJSON } from '../../utils/api';

interface DashboardProps {
  onNavigate: (page: string) => void;
}

interface Metrics {
  totalLeads: number | null;
  qualifiedLeads: number | null;
  emailsSent: number | null;
  replies: number | null;
  meetings: number | null;
  pipelineValue: number | null;
  activeSignals: number | null;
}

const WORKFLOW_STEPS = [
  { icon: '🔎', label: 'Prospecting',      page: 'prospecting', desc: 'Discover companies' },
  { icon: '🏢', label: 'Intelligence',      page: 'signals',     desc: 'Research targets' },
  { icon: '📡', label: 'Buying Signals',   page: 'signals',     desc: 'Detect intent' },
  { icon: '✉️',  label: 'Outreach',         page: 'outreach',    desc: 'Send emails' },
  { icon: '💬', label: 'Reply Handling',   page: 'replies',     desc: 'Qualify replies' },
  { icon: '📅', label: 'Meetings',         page: 'meetings',    desc: 'Book demos' },
  { icon: '📋', label: 'CRM',              page: 'crm',         desc: 'Track progress' },
  { icon: '📊', label: 'Pipeline',         page: 'pipeline',    desc: 'Forecast revenue' },
];

function MetricCard({
  icon, label, value, sub, color, onClick,
}: {
  icon: string; label: string; value: string | null;
  sub?: string; color?: string; onClick?: () => void;
}) {
  return (
    <div
      className="metric-card"
      onClick={onClick}
      style={{ cursor: onClick ? 'pointer' : 'default' }}
    >
      <div className="metric-label">
        <span style={{ fontSize: 16 }}>{icon}</span>
        {label}
      </div>
      <div
        className="metric-value"
        style={{ color: color || 'var(--text-primary)' }}
      >
        {value ?? <span style={{ fontSize: 16, color: 'var(--text-muted)', fontWeight: 500 }}>—</span>}
      </div>
      {sub && <div className="metric-sub">{sub}</div>}
    </div>
  );
}

export default function DashboardPage({ onNavigate }: DashboardProps) {
  const [metrics, setMetrics] = useState<Metrics>({
    totalLeads: null,
    qualifiedLeads: null,
    emailsSent: null,
    replies: null,
    meetings: null,
    pipelineValue: null,
    activeSignals: null,
  });
  const [agentStatus, setAgentStatus] = useState<string>('Unknown');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadMetrics = async () => {
      setLoading(true);
      try {
        // Fetch in parallel
        const [leadsData, pipelineData, campaignData, meetingsData] = await Promise.all([
          fetchJSON<{ leads: any[]; total: number }>('/leads?limit=1'),
          fetchJSON<any>('/pipeline/report'),
          fetchJSON<{ campaigns: any[]; total: number }>('/campaigns?limit=1'),
          fetchJSON<{ meetings: any[]; total: number }>('/meetings?limit=1'),
        ]);

        // Agent status
        const agentSettings = await fetchJSON<any>('/orchestration/settings');
        if (agentSettings) setAgentStatus(agentSettings.current_status || 'Idle');

        setMetrics({
          totalLeads: leadsData?.total ?? null,
          qualifiedLeads: pipelineData?.lead_funnel
            ? Object.values(pipelineData.lead_funnel as Record<string, number>).reduce((a, b) => a + b, 0)
            : null,
          emailsSent: pipelineData?.campaign_performance?.sent ?? null,
          replies: pipelineData?.campaign_performance?.replied ?? null,
          meetings: meetingsData?.total ?? null,
          pipelineValue: pipelineData?.pipeline_forecast?.total_value ?? null,
          activeSignals: null,
        });
      } catch (e) {
        console.error('Dashboard metrics load error', e);
      }
      setLoading(false);
    };

    loadMetrics();
  }, []);

  const fmt = (n: number | null, prefix = '') => {
    if (n === null) return null;
    if (prefix === '$') return `$${n.toLocaleString()}`;
    return n.toLocaleString();
  };

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 8 }}>
          <div style={{
            width: 44, height: 44,
            background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
            borderRadius: 12, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22, boxShadow: '0 4px 14px rgba(15,118,110,0.3)',
          }}>🤖</div>
          <div>
            <h1 style={{
              fontSize: 26, fontWeight: 800, color: 'var(--text-primary)',
              letterSpacing: '-0.03em', lineHeight: 1.1,
            }}>
              SETV AI Sales Agent
            </h1>
            <p style={{ fontSize: 14, color: 'var(--text-muted)', marginTop: 4 }}>
              AI-powered sales operations — prospect, engage, and close at scale.
            </p>
          </div>
          {/* Agent status pill */}
          <div style={{ marginLeft: 'auto' }}>
            <span className={`status-pill ${agentStatus === 'Running' ? 'running' : 'idle'}`}>
              <span
                className="agent-dot"
                style={{ width: 7, height: 7 }}
                data-status={agentStatus === 'Running' ? 'running' : 'idle'}
              />
              Agent {agentStatus}
            </span>
          </div>
        </div>
      </div>

      {/* Metrics grid */}
      <div className="grid-4" style={{ marginBottom: 32 }}>
        <MetricCard
          icon="🏢" label="Total Leads" value={fmt(metrics.totalLeads)}
          sub="In CRM" onClick={() => onNavigate('crm')}
        />
        <MetricCard
          icon="✉️" label="Emails Sent" value={fmt(metrics.emailsSent)}
          sub="Outreach campaigns" onClick={() => onNavigate('outreach')}
          color="var(--primary)"
        />
        <MetricCard
          icon="💬" label="Replies" value={fmt(metrics.replies)}
          sub="From prospects" onClick={() => onNavigate('replies')}
          color="var(--cyan)"
        />
        <MetricCard
          icon="📅" label="Meetings" value={fmt(metrics.meetings)}
          sub="Booked total" onClick={() => onNavigate('meetings')}
          color="var(--green)"
        />
      </div>

      <div className="grid-2" style={{ marginBottom: 32 }}>
        <MetricCard
          icon="💰" label="Pipeline Value" value={fmt(metrics.pipelineValue, '$')}
          sub="Total estimated value" onClick={() => onNavigate('pipeline')}
          color="var(--amber)"
        />
        <MetricCard
          icon="🤖" label="Agent Mode" value={agentStatus}
          sub="Click Agent Control to configure" onClick={() => onNavigate('agent')}
          color={agentStatus === 'Running' ? 'var(--amber)' : 'var(--text-muted)'}
        />
      </div>

      {/* Workflow visualization */}
      <div className="card" style={{ marginBottom: 28 }}>
        <div className="section-header">
          <div className="section-title">
            <span>🔄</span> Sales Workflow
          </div>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Click any step to navigate
          </span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20 }}>
          Each step feeds the next. The AI Agent can automate the entire pipeline autonomously.
        </p>
        <div className="workflow-flow">
          {WORKFLOW_STEPS.map((step, i) => (
            <div key={step.page + i} className="workflow-step">
              <div
                className="workflow-node"
                onClick={() => onNavigate(step.page)}
                title={step.desc}
              >
                <div className="workflow-node-icon">{step.icon}</div>
                <div className="workflow-node-label">{step.label}</div>
              </div>
              {i < WORKFLOW_STEPS.length - 1 && (
                <div className="workflow-arrow">→</div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Module guide */}
      <div className="card">
        <div className="section-title" style={{ marginBottom: 18 }}>
          <span>📖</span> Quick Module Guide
        </div>
        <div className="grid-2" style={{ marginBottom: 0 }}>
          {[
            { icon: '🔎', name: 'Prospecting',     desc: 'Define your ICP and let AI find qualified companies and decision makers across Apollo, NPI, and the web.',   page: 'prospecting' },
            { icon: '📡', name: 'Buying Signals',  desc: 'Detect hiring surges, funding rounds, leadership changes, and other events that indicate a company is ready to buy.',  page: 'signals' },
            { icon: '✉️',  name: 'Outreach',        desc: 'Generate highly personalized emails using company intelligence, signals, and your approved templates. Send via Gmail.', page: 'outreach' },
            { icon: '💬', name: 'Reply Handling',  desc: 'AI analyzes every reply for intent and sentiment, then drafts the appropriate response or escalates for approval.',    page: 'replies' },
            { icon: '📅', name: 'Meetings',        desc: 'Track interested leads through to booked meetings. Integrates with Google Calendar for scheduling and invites.',       page: 'meetings' },
            { icon: '📋', name: 'CRM',             desc: 'Full contact and company tracking with status progression, activity history, and company intelligence profiles.',       page: 'crm' },
            { icon: '📊', name: 'Pipeline',        desc: 'Visual sales funnel with conversion rates, weighted revenue forecast, risk flags, and AI-recommended next actions.',   page: 'pipeline' },
            { icon: '🤖', name: 'Agent Control',   desc: 'Set a goal and let the AI agent run the entire workflow autonomously — with configurable approval gates.',             page: 'agent' },
          ].map(m => (
            <div
              key={m.page}
              onClick={() => onNavigate(m.page)}
              style={{
                display: 'flex', gap: 14, padding: '14px 16px',
                borderRadius: 10, cursor: 'pointer', transition: 'all 0.15s',
                border: '1px solid var(--border)', background: 'var(--bg-card)',
              }}
              onMouseEnter={e => {
                (e.currentTarget as HTMLElement).style.borderColor = 'var(--primary-border)';
                (e.currentTarget as HTMLElement).style.background = 'var(--primary-light)';
              }}
              onMouseLeave={e => {
                (e.currentTarget as HTMLElement).style.borderColor = 'var(--border)';
                (e.currentTarget as HTMLElement).style.background = 'var(--bg-card)';
              }}
            >
              <span style={{ fontSize: 22, flexShrink: 0, marginTop: 2 }}>{m.icon}</span>
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
                  {m.name}
                </div>
                <div style={{ fontSize: 12.5, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                  {m.desc}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
