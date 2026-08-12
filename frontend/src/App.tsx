import React, { useState } from 'react';
import ProspectingPage from './app/prospecting/ProspectingPage';
import SignalsPage from './app/signals/SignalsPage';
import OutreachPage from './app/outreach/OutreachPage';
import ReplyHandlingPage from './app/replies/ReplyHandlingPage';
import MeetingsPage from './app/meetings/MeetingsPage';
import CRMPage from './app/crm/CRMPage';
import PipelinePage from './app/pipeline/PipelinePage';
import AgentControlPage from './app/agent/AgentControlPage';
import DashboardPage from './app/dashboard/DashboardPage';
import AgentStatusSidebar from './components/common/AgentStatusSidebar';

type Page = 'dashboard' | 'agent' | 'prospecting' | 'signals' | 'outreach' | 'replies' | 'meetings' | 'crm' | 'pipeline';

interface NavItem {
  key: Page;
  icon: string;
  label: string;
  tooltip: string;
}

const WORKFLOW_NAV: NavItem[] = [
  { key: 'agent',       icon: '🤖', label: 'Agent Control',    tooltip: 'Autonomously coordinate the sales workflow.' },
  { key: 'prospecting', icon: '🔎', label: 'Prospecting',       tooltip: 'Discover qualified companies and decision makers.' },
  { key: 'signals',     icon: '📡', label: 'Buying Signals',    tooltip: 'Detect events that indicate buying intent.' },
  { key: 'outreach',    icon: '✉️',  label: 'Outreach',          tooltip: 'Generate and send personalized sales emails.' },
  { key: 'replies',     icon: '💬', label: 'Reply Handling',    tooltip: 'Analyze responses and prepare next actions.' },
  { key: 'meetings',    icon: '📅', label: 'Meetings',          tooltip: 'Manage scheduling and calendar bookings.' },
  { key: 'crm',         icon: '📋', label: 'CRM',               tooltip: 'Track contacts, activities, and sales stages.' },
  { key: 'pipeline',    icon: '📊', label: 'Pipeline',          tooltip: 'Monitor opportunities and revenue forecast.' },
];

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');

  return (
    <div className="app">
      {/* ── Sidebar ── */}
      <div className="sidebar">
        {/* Logo */}
        <div className="sidebar-header">
          <div className="sidebar-logo">
            <div className="sidebar-logo-mark">S</div>
            <div className="sidebar-logo-text">
              <div className="sidebar-logo-name">SETV</div>
              <div className="sidebar-logo-sub">AI Sales Agent</div>
            </div>
          </div>
        </div>

        <div className="sidebar-nav">
          {/* Dashboard */}
          <div
            className={`nav-item ${page === 'dashboard' ? 'active' : ''}`}
            onClick={() => setPage('dashboard')}
          >
            <span className="nav-icon">🏠</span>
            Dashboard
            <span className="nav-tooltip">Platform overview and key metrics.</span>
          </div>

          {/* Workflow section */}
          <div className="sidebar-section">Workflow</div>
          {WORKFLOW_NAV.map(n => (
            <div
              key={n.key}
              className={`nav-item ${page === n.key ? 'active' : ''}`}
              onClick={() => setPage(n.key)}
            >
              <span className="nav-icon">{n.icon}</span>
              {n.label}
              <span className="nav-tooltip">{n.tooltip}</span>
            </div>
          ))}
        </div>

        {/* Agent Status */}
        <AgentStatusSidebar />
      </div>

      {/* ── Main ── */}
      <div className="main">
        {page === 'dashboard'   && <DashboardPage onNavigate={(p) => setPage(p as Page)} />}
        {page === 'agent'       && <AgentControlPage />}
        {page === 'prospecting' && <ProspectingPage />}
        {page === 'signals'     && <SignalsPage />}
        {page === 'outreach'    && <OutreachPage />}
        {page === 'replies'     && <ReplyHandlingPage />}
        {page === 'meetings'    && <MeetingsPage />}
        {page === 'crm'         && <CRMPage />}
        {page === 'pipeline'    && <PipelinePage />}
      </div>
    </div>
  );
}
