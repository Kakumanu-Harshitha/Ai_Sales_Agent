import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';


export function StatusBadge({ status }: { status?: string }) {
  const s = (status || '').toLowerCase().replace(/ /g, '_');
  const colors: Record<string, string> = {
    new: 'badge-blue', scored: 'badge-purple', contacted: 'badge-amber',
    replied: 'badge-cyan', meeting_booked: 'badge-green', proposal_sent: 'badge-amber',
    closed_won: 'badge-green', closed_lost: 'badge-red', scheduled: 'badge-blue',
    active: 'badge-green', draft: 'badge-gray', sent: 'badge-blue',
    interested: 'badge-green', not_interested: 'badge-red', demo_request: 'badge-cyan',
    meeting_request: 'badge-green', pricing_request: 'badge-amber', follow_up_later: 'badge-gray',
    idle: 'badge-gray', running: 'badge-amber', completed: 'badge-green',
    high: 'badge-red', medium: 'badge-amber', low: 'badge-gray',
    positive: 'badge-green', neutral: 'badge-gray', negative: 'badge-red',
  };
  return <span className={`badge ${colors[s] || 'badge-gray'}`}>{status || 'N/A'}</span>;
}

export function ScoreBar({ score }: { score?: number }) {
  const pct = Math.min(Math.max(score || 0, 0), 100);
  const color = pct >= 70 ? 'var(--green)' : pct >= 40 ? 'var(--amber)' : 'var(--red)';
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="score-bar"><span className="score-fill" style={{ width: `${pct}%`, background: color }} /></span>
      <span style={{ fontSize: 13, fontWeight: 700, color }}>{pct}</span>
    </span>
  );
}

export function Spinner() { return <div className="loading"><div className="spinner" />Loading...</div>; }

