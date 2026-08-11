import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut, AgentGoal, AgentDecision, AgentReflection } from './types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from './utils/api';

import ProspectingPage from './app/prospecting/ProspectingPage';
import SignalsPage from './app/signals/SignalsPage';
import OutreachPage from './app/outreach/OutreachPage';
import ReplyHandlingPage from './app/replies/ReplyHandlingPage';
import MeetingsPage from './app/meetings/MeetingsPage';
import CRMPage from './app/crm/CRMPage';
import PipelinePage from './app/pipeline/PipelinePage';
import AgentControlPage from './app/agent/AgentControlPage';
import AgentStatusSidebar from './components/common/AgentStatusSidebar';

import { StatusBadge, ScoreBar, Spinner } from './components/common/Shared';


type Page = 'prospecting' | 'signals' | 'outreach' | 'replies' | 'meetings' | 'crm' | 'pipeline' | 'agent';

export default function App() {
  const [page, setPage] = useState<Page>('prospecting');

  const navItems: { key: Page; icon: string; label: string }[] = [
    { key: 'agent', icon: '🤖', label: 'Agent Control' },
    { key: 'prospecting', icon: '🔍', label: 'Prospecting' },
    { key: 'signals', icon: '📡', label: 'Buying Signals' },
    { key: 'outreach', icon: '📧', label: 'Outreach' },
    { key: 'replies', icon: '💬', label: 'Reply Handling' },
    { key: 'meetings', icon: '📅', label: 'Meetings' },
    { key: 'crm', icon: '📋', label: 'CRM' },
    { key: 'pipeline', icon: '📊', label: 'Pipeline' },
  ];

  return (
    <>
      <div className="app">
        <div className="sidebar">
          <div className="sidebar-logo">SETV<span>AI Sales Agent</span></div>
          <div className="sidebar-section">Workflow</div>
          {navItems.map(n => (
            <div key={n.key} className={`nav-item ${page === n.key ? 'active' : ''}`} onClick={() => setPage(n.key)}>
              <span className="nav-icon">{n.icon}</span>{n.label}
            </div>
          ))}
          <AgentStatusSidebar />
        </div>
        <div className="main">
                    {page === 'agent' && <AgentControlPage />}
          {page === 'prospecting' && <ProspectingPage />}
          {page === 'signals' && <SignalsPage />}
          {page === 'outreach' && <OutreachPage />}
          {page === 'replies' && <ReplyHandlingPage />}
          {page === 'meetings' && <MeetingsPage />}
          {page === 'crm' && <CRMPage />}
          {page === 'pipeline' && <PipelinePage />}
        </div>
      </div>
    </>
  );
}

