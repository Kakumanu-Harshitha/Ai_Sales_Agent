import React from 'react';

export function StatusBadge({ status }: { status?: string }) {
  const s = (status || '').toLowerCase().replace(/ /g, '_');
  const colors: Record<string, string> = {
    // Lead statuses
    new: 'badge-blue',
    discovered: 'badge-blue',
    scored: 'badge-teal',
    contacted: 'badge-amber',
    outreach_pending: 'badge-amber',
    replied: 'badge-cyan',
    meeting_booked: 'badge-green',
    proposal_sent: 'badge-amber',
    closed_won: 'badge-green',
    won: 'badge-green',
    closed_lost: 'badge-red',
    lost: 'badge-red',
    // Campaign / email
    scheduled: 'badge-blue',
    active: 'badge-green',
    draft: 'badge-gray',
    sent: 'badge-teal',
    // Reply intent
    interested: 'badge-green',
    not_interested: 'badge-red',
    demo_request: 'badge-cyan',
    meeting_request: 'badge-green',
    pricing_request: 'badge-amber',
    follow_up_later: 'badge-gray',
    out_of_office: 'badge-gray',
    question: 'badge-blue',
    follow_up: 'badge-amber',
    // Agent decisions
    pending_approval: 'badge-amber',
    executed: 'badge-green',
    approved: 'badge-green',
    skipped: 'badge-gray',
    failed: 'badge-red',
    // Priority
    high: 'badge-red',
    medium: 'badge-amber',
    low: 'badge-gray',
    // Sentiment
    positive: 'badge-green',
    neutral: 'badge-gray',
    negative: 'badge-red',
    // Agent status
    idle: 'badge-gray',
    running: 'badge-amber',
    completed: 'badge-green',
    // Meeting
    pending: 'badge-amber',
    confirmed: 'badge-green',
    cancelled: 'badge-red',
  };
  return <span className={`badge ${colors[s] || 'badge-gray'}`}>{status || 'N/A'}</span>;
}

export function ScoreBar({ score }: { score?: number }) {
  const pct = Math.min(Math.max(score || 0, 0), 100);
  const color = pct >= 70 ? 'var(--green)' : pct >= 40 ? 'var(--amber)' : 'var(--red)';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="score-bar">
        <span className="score-fill" style={{ width: `${pct}%`, background: color }} />
      </span>
      <span style={{ fontSize: 12, fontWeight: 700, color }}>{pct}</span>
    </span>
  );
}

export function Spinner({ text }: { text?: string }) {
  return (
    <div className="loading">
      <div className="spinner" />
      {text || 'Loading...'}
    </div>
  );
}

export function EmptyState({
  icon, title, description, action,
}: {
  icon?: string; title: string; description?: string; action?: React.ReactNode;
}) {
  return (
    <div className="empty-state">
      {icon && <div className="empty-state-icon">{icon}</div>}
      <div className="empty-state-title">{title}</div>
      {description && <p style={{ fontSize: 13, maxWidth: 360, marginTop: 4 }}>{description}</p>}
      {action && <div style={{ marginTop: 16 }}>{action}</div>}
    </div>
  );
}
