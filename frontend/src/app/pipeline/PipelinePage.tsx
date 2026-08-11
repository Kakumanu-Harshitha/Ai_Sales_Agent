import React, { useState, useEffect, useCallback, useRef } from 'react';
import { Lead, Campaign, Meeting, Activity, Signal, Call, Note, SignatureTemplate, EmailRecord, Reply, Contact, Company, LeadFullDetail, AgentStatus, PipelineReport, CompanyIntelligenceOut } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate, getLeadDisplayName, API } from '../../utils/api';
import { StatusBadge, ScoreBar, Spinner } from '../../components/common/Shared';


export default function PipelinePage() {
  const [report, setReport] = useState<PipelineReport | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const data = await fetchJSON<PipelineReport>('/pipeline/report');
    setReport(data);
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  if (loading) return <Spinner />;
  if (!report) return <div className="loading">Failed to load pipeline report. Ensure backend is running.</div>;

  const funnelStages = ['new', 'scored', 'contacted', 'replied', 'meeting_booked', 'proposal_sent', 'closed_won', 'closed_lost'];
  const maxFunnel = Math.max(...funnelStages.map(s => report.lead_funnel[s] || 0), 1);

  return (
    <>
      <div className="page-header">
        <div><div className="page-title">📊 Pipeline Intelligence</div><div className="page-subtitle">Real-time analytics calculated from PostgreSQL — no hardcoded values</div></div>
        <button className="btn btn-primary" onClick={load}>↻ Refresh</button>
      </div>

      <div className="grid-4">
        <div className="card"><div className="card-title">Pipeline Value</div><div className="card-value blue">${report.pipeline_forecast.total_value.toLocaleString()}</div></div>
        <div className="card"><div className="card-title">Weighted Value</div><div className="card-value green">${report.pipeline_forecast.weighted_value.toLocaleString()}</div></div>
        <div className="card"><div className="card-title">Expected Revenue</div><div className="card-value green">${report.revenue_forecast.expected_revenue.toLocaleString()}</div></div>
        <div className="card"><div className="card-title">Close Probability</div><div className="card-value amber">{report.pipeline_forecast.close_probability}%</div></div>
      </div>

      <div className="grid-2">
        <div className="card">
          <div className="card-title">Lead Funnel</div>
          <div className="funnel" style={{ marginTop: 20 }}>
            {funnelStages.map((stage, i) => (
              <div className="funnel-row" key={stage}>
                <div className="funnel-label">{stage.replace(/_/g, ' ')}</div>
                <div className="funnel-bar">
                  <div className={`funnel-fill stage-${i}`} style={{ width: `${Math.max(((report.lead_funnel[stage] || 0) / maxFunnel) * 100, 4)}%` }}>
                    {report.lead_funnel[stage] || 0}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="card">
          <div className="card-title">Conversion Rates</div>
          <div className="funnel" style={{ marginTop: 20 }}>
            <div className="funnel-row">
              <div className="funnel-label">Outreach → Reply</div>
              <div className="funnel-bar"><div className="funnel-fill stage-2" style={{ width: `${Math.max(report.conversion_rate.outreach_to_reply, 4)}%` }}>{report.conversion_rate.outreach_to_reply}%</div></div>
            </div>
            <div className="funnel-row">
              <div className="funnel-label">Reply → Meeting</div>
              <div className="funnel-bar"><div className="funnel-fill stage-3" style={{ width: `${Math.max(report.conversion_rate.reply_to_meeting, 4)}%` }}>{report.conversion_rate.reply_to_meeting}%</div></div>
            </div>
            <div className="funnel-row">
              <div className="funnel-label">Meeting → Close</div>
              <div className="funnel-bar"><div className="funnel-fill stage-6" style={{ width: `${Math.max(report.conversion_rate.meeting_to_close, 4)}%` }}>{report.conversion_rate.meeting_to_close}%</div></div>
            </div>
          </div>

          <div style={{ marginTop: 32 }}>
            <div className="card-title">Campaign Performance</div>
            <div className="grid-4" style={{ marginTop: 16, marginBottom: 0 }}>
              <div><div style={{ fontSize: 28, fontWeight: 700 }}>{report.campaign_performance.sent}</div><div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Sent</div></div>
              <div><div style={{ fontSize: 28, fontWeight: 700 }}>{report.campaign_performance.opened}</div><div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Opened</div></div>
              <div><div style={{ fontSize: 28, fontWeight: 700 }}>{report.campaign_performance.clicked}</div><div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Clicked</div></div>
              <div><div style={{ fontSize: 28, fontWeight: 700 }}>{report.campaign_performance.replied}</div><div style={{ fontSize: 13, color: 'var(--text-muted)' }}>Replied</div></div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid-3">
        <div className="card">
          <div className="card-title">⚠️ Risk Flags ({report.risk_flags.length})</div>
          <div className="alert-list" style={{ marginTop: 16 }}>
            {report.risk_flags.length === 0 ? <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>No risk flags ✓</div> : report.risk_flags.map((f, i) => <div key={i} className="alert-item alert-risk">{f}</div>)}
          </div>
        </div>
        <div className="card">
          <div className="card-title">🐌 Stalled Deals ({report.stalled_deals.length})</div>
          <div className="alert-list" style={{ marginTop: 16 }}>
            {report.stalled_deals.length === 0 ? <div style={{ color: 'var(--text-muted)', fontSize: 14 }}>No stalled deals ✓</div> : report.stalled_deals.map((d, i) => <div key={i} className="alert-item alert-stalled">{d}</div>)}
          </div>
        </div>
        <div className="card">
          <div className="card-title">🎯 Next Best Actions</div>
          <div className="alert-list" style={{ marginTop: 16 }}>
            {report.next_best_actions.map((a, i) => <div key={i} className="alert-item alert-action">{a}</div>)}
          </div>
        </div>
      </div>
    </>
  );
}

