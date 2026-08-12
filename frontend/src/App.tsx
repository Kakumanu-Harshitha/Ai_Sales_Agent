import React, { useState, useEffect } from 'react';
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
  const [mountedPages, setMountedPages] = useState<Partial<Record<Page, boolean>>>({
    dashboard: true,
  });

  useEffect(() => {
    if (!mountedPages[page]) {
      setMountedPages(prev => ({ ...prev, [page]: true }));
    }
  }, [page, mountedPages]);

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
        {mountedPages.dashboard && (
          <div style={{ display: page === 'dashboard' ? 'block' : 'none' }}>
            <DashboardPage onNavigate={(p) => setPage(p as Page)} />
          </div>
        )}
        {mountedPages.agent && (
          <div style={{ display: page === 'agent' ? 'block' : 'none' }}>
            <AgentControlPage />
          </div>
        )}
        {mountedPages.prospecting && (
          <div style={{ display: page === 'prospecting' ? 'block' : 'none' }}>
            <ProspectingPage />
          </div>
        )}
        {mountedPages.signals && (
          <div style={{ display: page === 'signals' ? 'block' : 'none' }}>
            <SignalsPage />
          </div>
        )}
        {mountedPages.outreach && (
          <div style={{ display: page === 'outreach' ? 'block' : 'none' }}>
            <OutreachPage />
          </div>
        )}
        {mountedPages.replies && (
          <div style={{ display: page === 'replies' ? 'block' : 'none' }}>
            <ReplyHandlingPage />
          </div>
        )}
        {mountedPages.meetings && (
          <div style={{ display: page === 'meetings' ? 'block' : 'none' }}>
            <MeetingsPage />
          </div>
        )}
        {mountedPages.crm && (
          <div style={{ display: page === 'crm' ? 'block' : 'none' }}>
            <CRMPage />
          </div>
        )}
        {mountedPages.pipeline && (
          <div style={{ display: page === 'pipeline' ? 'block' : 'none' }}>
            <PipelinePage />
          </div>
        )}
      </div>
    </div>
  );
}
