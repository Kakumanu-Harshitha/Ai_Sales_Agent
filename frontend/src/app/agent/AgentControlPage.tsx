import React, { useState, useEffect, useCallback } from 'react';
import { AgentGoal, AgentDecision, AgentReflection } from '../../types';
import { fetchJSON, postJSON, timeAgo, fmtDate } from '../../utils/api';
import { StatusBadge, Spinner } from '../../components/common/Shared';
import KnowledgeTab from './KnowledgeTab';

// ── Action display helpers ────────────────────────────────────────────────────
const ACTION_LABELS: Record<string, { icon: string; label: string; color: string }> = {
  discover_more_leads:    { icon: '🔍', label: 'Discover Leads',     color: 'var(--blue)' },
  rescan_signals:         { icon: '📡', label: 'Rescan Signals',     color: 'var(--cyan)' },
  re_enrich_lead:         { icon: '🔬', label: 'Re-Enrich Contact',  color: 'var(--accent-glow)' },
  send_initial_outreach:  { icon: '📧', label: 'Send Outreach',      color: 'var(--green)' },
  send_followup:          { icon: '🔁', label: 'Send Follow-Up',     color: 'var(--amber)' },
  revise_template:        { icon: '✍️',  label: 'Revise Template',   color: '#c084fc' },
  do_nothing_this_cycle:  { icon: '⏸️', label: 'No Action',         color: 'var(--text-muted)' },
  book_meeting:           { icon: '📅', label: 'Book Meeting',       color: 'var(--green)' },
};

function ActionBadge({ action }: { action: string }) {
  const meta = ACTION_LABELS[action] || { icon: '⚡', label: action, color: 'var(--text-muted)' };
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 10px',
      borderRadius: 999, fontSize: 12, fontWeight: 600,
      background: `${meta.color}18`, color: meta.color, border: `1px solid ${meta.color}33`,
    }}>
      {meta.icon} {meta.label}
    </span>
  );
}

function GoalProgressBar({ current, target }: { current: number; target: number }) {
  const pct = target > 0 ? Math.min((current / target) * 100, 100) : 0;
  const color = pct >= 100 ? 'var(--green)' : pct >= 50 ? 'var(--amber)' : 'var(--red)';
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, fontSize: 13 }}>
        <span style={{ color: 'var(--text-secondary)' }}>Progress this period</span>
        <span style={{ fontWeight: 700, color }}>{current} / {target}</span>
      </div>
      <div style={{ height: 8, background: 'var(--bg-card-hover)', borderRadius: 4, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${pct}%`, background: color,
          borderRadius: 4, transition: 'width 0.6s ease',
        }} />
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>{pct.toFixed(0)}% of goal</div>
    </div>
  );
}

function Toggle({ checked, onChange, label, sublabel }: {
  checked: boolean; onChange: (v: boolean) => void; label: string; sublabel?: string;
}) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      padding: '8px 12px', background: 'var(--bg-card-hover)', minHeight: 48,
      borderRadius: 8, border: `1px solid ${checked ? 'rgba(99,102,241,0.3)' : 'var(--border)'}`,
      cursor: 'pointer', transition: 'border-color 0.2s',
    }} onClick={() => onChange(!checked)}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)' }}>{label}</div>
        {sublabel && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{sublabel}</div>}
      </div>
      <div style={{
        width: 36, height: 20, borderRadius: 10, position: 'relative',
        background: checked ? 'var(--accent)' : 'var(--border)',
        transition: 'background 0.2s', flexShrink: 0,
      }}>
        <div style={{
          position: 'absolute', top: 2, left: checked ? 18 : 2, width: 16, height: 16,
          borderRadius: '50%', background: 'white', transition: 'left 0.2s',
          boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
        }} />
      </div>
    </div>
  );
}

// ── Outreach Strategy Selector ─────────────────────────────────────────────
type OutreachStrategy = 'fixed' | 'rotate' | 'ai_select';

const STRATEGY_OPTIONS: { value: OutreachStrategy; label: string; icon: string; description: string; color: string }[] = [
  {
    value: 'fixed',
    icon: '📌',
    label: 'Fixed Template',
    description: 'Always use the selected default template. Predictable and consistent.',
    color: 'var(--cyan)',
  },
  {
    value: 'rotate',
    icon: '🔄',
    label: 'Rotate Templates',
    description: 'Cycle through all available templates sequentially. Good for A/B testing.',
    color: 'var(--amber)',
  },
  {
    value: 'ai_select',
    icon: '🤖',
    label: 'AI Select Best Template',
    description: 'The Agent Controller automatically picks the best template based on your Goal, previous campaign performance, and Agent Memory. Fully autonomous.',
    color: 'var(--accent)',
  },
];

function OutreachStrategySelector({ value, onChange }: {
  value: OutreachStrategy; onChange: (v: OutreachStrategy) => void;
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {STRATEGY_OPTIONS.map(opt => {
        const isActive = value === opt.value;
        return (
          <div
            key={opt.value}
            onClick={() => onChange(opt.value)}
            style={{
              padding: '14px 16px',
              borderRadius: 10,
              border: `2px solid ${isActive ? opt.color : 'var(--border)'}`,
              background: isActive ? `${opt.color}0f` : 'var(--bg-card-hover)',
              cursor: 'pointer',
              transition: 'all 0.2s',
              display: 'flex',
              alignItems: 'flex-start',
              gap: 12,
            }}
          >
            {/* Radio indicator */}
            <div style={{
              width: 18, height: 18, borderRadius: '50%', flexShrink: 0, marginTop: 2,
              border: `2px solid ${isActive ? opt.color : 'var(--border)'}`,
              background: isActive ? opt.color : 'transparent',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              transition: 'all 0.2s',
            }}>
              {isActive && <div style={{ width: 6, height: 6, borderRadius: '50%', background: 'white' }} />}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <span style={{ fontSize: 16 }}>{opt.icon}</span>
                <span style={{
                  fontSize: 14, fontWeight: 600,
                  color: isActive ? opt.color : 'var(--text-primary)',
                }}>
                  {opt.label}
                </span>
                {opt.value === 'ai_select' && (
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 999,
                    background: 'rgba(99,102,241,0.2)', color: 'var(--accent)',
                    textTransform: 'uppercase', letterSpacing: '0.06em',
                  }}>
                    Agentic
                  </span>
                )}
              </div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.5 }}>
                {opt.description}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Confidence Badge ──────────────────────────────────────────────────────────
function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color = pct >= 80 ? 'var(--green)' : pct >= 60 ? 'var(--amber)' : 'var(--red)';
  return (
    <span style={{
      fontSize: 12, fontWeight: 700, padding: '2px 9px', borderRadius: 999,
      background: `${color}18`, color, border: `1px solid ${color}33`,
    }}>
      {pct}% confidence
    </span>
  );
}

// ── Tab 1: Status & Goal ───────────────────────────────────────────────────────
function StatusGoalTab({ settings, goal, systemLogs, onGoalSave, onSettingsUpdate }: {
  settings: any; goal: AgentGoal | null; systemLogs: string[]; onGoalSave: (g: Partial<AgentGoal>) => Promise<void>;
  onSettingsUpdate: (u: any) => Promise<void>;
}) {
  const [draft, setDraft] = useState<Partial<AgentGoal>>(goal || {});
  const [settingsDraft, setSettingsDraft] = useState<any>(settings || {});
  const [savingLeft, setSavingLeft] = useState(false);
  const [savingRight, setSavingRight] = useState(false);

  useEffect(() => { if (goal) setDraft(goal); }, [goal]);
  useEffect(() => { if (settings) setSettingsDraft(settings); }, [settings]);

  const handleSaveLeft = async () => {
    setSavingLeft(true);
    await onGoalSave(draft);
    if (settingsDraft.outreach_strategy !== settings?.outreach_strategy || settingsDraft.interval_minutes !== settings?.interval_minutes) {
      await onSettingsUpdate({ outreach_strategy: settingsDraft.outreach_strategy, interval_minutes: settingsDraft.interval_minutes });
    }
    setTimeout(() => setSavingLeft(false), 1000);
  };

  const handleSaveRight = async () => {
    setSavingRight(true);
    await onGoalSave(draft);
    if (
      settingsDraft.auto_send_emails !== settings?.auto_send_emails ||
      settingsDraft.reply_monitoring !== settings?.reply_monitoring
    ) {
      await onSettingsUpdate({
        auto_send_emails: settingsDraft.auto_send_emails,
        reply_monitoring: settingsDraft.reply_monitoring
      });
    }
    setTimeout(() => setSavingRight(false), 1000);
  };

  return (
    <div className="agent-control-layout">
      {/* LEFT: Goal Config */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="card">
          <h3 className="card-title" style={{ marginBottom: 20 }}>🎯 Agent Goal</h3>

          <div className="responsive-grid-2" style={{ marginBottom: 16 }}>
            <div className="form-group">
              <label className="form-label">Target Metric</label>
              <select
                value={draft.target_metric || 'meetings_booked'}
                onChange={e => setDraft(d => ({ ...d, target_metric: e.target.value as AgentGoal['target_metric'] }))}
              >
                <option value="meetings_booked">Meetings Booked</option>
                <option value="leads_qualified">Leads Qualified</option>
                <option value="leads_persisted">Leads Persisted</option>
                <option value="replies_received">Replies Received</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Target Value</label>
              <input type="number" value={draft.target_value || 10} min={1}
                onChange={e => setDraft(d => ({ ...d, target_value: parseInt(e.target.value) || 10 }))} />
            </div>
          </div>

          <div className="responsive-grid-2" style={{ marginBottom: 16 }}>
            <div className="form-group">
              <label className="form-label">Period</label>
              <select value={draft.period || 'weekly'}
                onChange={e => setDraft(d => ({ ...d, period: e.target.value as 'weekly' | 'daily' }))}>
                <option value="weekly">Weekly</option>
                <option value="daily">Daily</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Reflect Every N Cycles</label>
              <input type="number" value={draft.reflect_every_n_cycles || 1} min={1}
                onChange={e => setDraft(d => ({ ...d, reflect_every_n_cycles: parseInt(e.target.value) || 1 }))} />
            </div>
          </div>

          <div className="responsive-grid-2" style={{ marginBottom: 16 }}>
            <div className="form-group">
              <label className="form-label">Reply Rate Floor (%)</label>
              <input type="number" value={draft.reply_rate_floor ? (draft.reply_rate_floor * 100).toFixed(0) : 5} min={1} max={100}
                onChange={e => setDraft(d => ({ ...d, reply_rate_floor: parseFloat(e.target.value) / 100 || 0.05 }))} />
            </div>
            <div className="form-group">
              <label className="form-label">Min Sample for Revision</label>
              <input type="number" value={draft.min_sample_for_revision || 5} min={1}
                onChange={e => setDraft(d => ({ ...d, min_sample_for_revision: parseInt(e.target.value) || 5 }))} />
            </div>
          </div>

          <div className="responsive-grid-2" style={{ marginBottom: 20 }}>
            <div className="form-group">
              <label className="form-label">Outreach Strategy</label>
              <select value={settingsDraft?.outreach_strategy || 'fixed'}
                onChange={e => setSettingsDraft((d: any) => ({ ...d, outreach_strategy: e.target.value }))}>
                <option value="fixed">Fixed Template</option>
                <option value="rotate">Rotate Templates</option>
                <option value="ai_select">AI Select Best</option>
              </select>
            </div>
            <div className="form-group">
              <label className="form-label">Run Interval (mins)</label>
              <input type="number" value={settingsDraft?.interval_minutes || 10} min={1}
                onChange={e => setSettingsDraft((d: any) => ({ ...d, interval_minutes: parseInt(e.target.value) || 10 }))} />
            </div>
          </div>

          <button className="btn btn-primary" style={{ width: '100%' }} onClick={handleSaveLeft} disabled={savingLeft}>
            {savingLeft ? 'Saved!' : 'Save Config'}
          </button>
        </div>

        {goal && (
          <div className="card">
            <GoalProgressBar current={goal.current_value || 0} target={goal.target_value} />
          </div>
        )}
      </div>

      {/* RIGHT: Status + Autonomy Dial */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div className="card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 16 }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', marginBottom: 4, fontWeight: 600 }}>System Status</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <span className={`agent-dot ${settings?.current_status === 'Running' ? 'running' : 'idle'}`} style={{ width: 12, height: 12 }} />
                  <span style={{ fontSize: 24, fontWeight: 700 }}>{settings?.current_status || 'Unknown'}</span>
                </div>
                {settings?.current_stage && (
                  <div style={{ fontSize: 13, color: 'var(--accent)', marginTop: 4 }}>Stage: {settings.current_stage}</div>
                )}
              </div>
              <button
                className={`btn ${settings?.enabled ? 'btn-red' : 'btn-primary'}`}
                style={{ padding: '8px 16px', fontSize: 13 }}
                onClick={() => onSettingsUpdate({ enabled: !settings?.enabled })}
              >
                {settings?.enabled ? '⏹ Stop Agent' : '▶ Start Agent'}
              </button>
            </div>
            <div style={{ textAlign: 'right', display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Last Run</div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{fmtDate(settings?.last_run) || 'Never'}</div>
              </div>
              <div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Next Run</div>
                <div style={{ fontSize: 13, fontWeight: 500 }}>{fmtDate(settings?.next_run) || 'N/A'}</div>
              </div>
            </div>
          </div>
        </div>

        {goal && (
          <div className="card">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
              <h3 className="card-title" style={{ margin: 0 }}>🎛️ Autonomy Dial</h3>
              <button className="btn btn-primary" style={{ padding: '6px 12px', fontSize: 12 }} onClick={handleSaveRight} disabled={savingRight}>
                {savingRight ? 'Saved!' : 'Save Autonomy'}
              </button>
            </div>
            <div className="responsive-grid-2">
              <Toggle
                label="Re-scan Signals"
                sublabel="Safe — always autonomous"
                checked={draft.auto_rescan_signals ?? true}
                onChange={v => setDraft(d => ({ ...d, auto_rescan_signals: v }))}
              />
              <Toggle
                label="Re-Enrich Contacts"
                sublabel="Safe — always autonomous"
                checked={draft.auto_re_enrich_lead ?? true}
                onChange={v => setDraft(d => ({ ...d, auto_re_enrich_lead: v }))}
              />
              <Toggle
                label="Revise Templates"
                sublabel="Risky — requires approval"
                checked={draft.auto_revise_template ?? false}
                onChange={v => setDraft(d => ({ ...d, auto_revise_template: v }))}
              />
              <Toggle
                label="Book Meetings"
                sublabel="Risky — requires approval"
                checked={draft.auto_book_meeting ?? false}
                onChange={v => setDraft(d => ({ ...d, auto_book_meeting: v }))}
              />
              
              <Toggle
                label="Auto Send Emails"
                sublabel="Linked to Settings"
                checked={settingsDraft.auto_send_emails ?? false}
                onChange={v => setSettingsDraft((d: any) => ({ ...d, auto_send_emails: v }))}
              />
              <Toggle
                label="Reply Monitoring"
                sublabel="Linked to Settings"
                checked={settingsDraft.reply_monitoring ?? false}
                onChange={v => setSettingsDraft((d: any) => ({ ...d, reply_monitoring: v }))}
              />
            </div>
          </div>
        )}
        
        {/* Logs Area */}
        <div className="card" style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          <h3 className="card-title" style={{ marginBottom: 16 }}>📋 Recent Activity</h3>
          <div style={{ background: '#0d1117', padding: 16, borderRadius: 8, border: '1px solid var(--border)', fontFamily: 'monospace', fontSize: 12, height: 250, overflowY: 'auto' }}>
            {systemLogs?.length > 0 ? (
              systemLogs.map((log: string, i: number) => (
                <div key={i} style={{ padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.05)', color: log.includes('ERROR') || log.includes('WARNING') ? 'var(--red)' : 'var(--text-primary)' }}>
                  {log}
                </div>
              ))
            ) : (
              <div style={{ color: 'var(--text-muted)', fontStyle: 'italic' }}>No logs available yet. Start the agent to begin tracking.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Tab 2: Decision Log ────────────────────────────────────────────────────────
function DecisionLogTab({ decisions, onApprove, onRefresh, loading }: {
  decisions: AgentDecision[]; onApprove: (id: number) => void; onRefresh: () => void; loading: boolean;
}) {
  const [expanded, setExpanded] = useState<number | null>(null);

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h3 style={{ fontSize: 18, fontWeight: 600 }}>Decision Log</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
            Every action the agent decided to take — with reasoning. This is how you know it's agentic.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={onRefresh} disabled={loading}>↻ Refresh</button>
      </div>

      {loading ? <Spinner /> : decisions.length === 0 ? (
        <div className="empty-state">No decisions logged yet. Enable the agent to start a cycle.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {decisions.map(d => {
            const isExpanded = expanded === d.id;
            const isPending = d.status === 'pending_approval';
            const isOutreach = d.chosen_action === 'send_initial_outreach';

            // Parse outcome for template info
            let outcomeObj: any = {};
            try { outcomeObj = typeof d.outcome === 'string' ? JSON.parse(d.outcome) : (d.outcome || {}); } catch {}

            const selectedTemplate = outcomeObj?.selected_template;
            const templateConf = outcomeObj?.template_confidence;
            const templateReasoning = outcomeObj?.template_reasoning;

            return (
              <div key={d.id} className="card" style={{
                borderLeft: isPending ? '3px solid var(--amber)' : d.status === 'failed' ? '3px solid var(--red)' : '3px solid transparent',
                padding: 20,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
                  <div style={{ flex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 8 }}>
                      <ActionBadge action={d.chosen_action} />
                      <StatusBadge status={d.status} />
                      {d.goal_progress && (
                        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                          Goal: {d.goal_progress.current}/{d.goal_progress.target} ({d.goal_progress.pct}%)
                        </span>
                      )}
                    </div>

                    {/* ── Enhanced outreach decision block ── */}
                    {isOutreach && selectedTemplate && (
                      <div style={{
                        background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.2)',
                        borderRadius: 10, padding: '14px 16px', marginBottom: 10,
                      }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
                          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--accent)' }}>
                            📋 Selected Template
                          </span>
                          <span style={{
                            fontSize: 13, fontWeight: 600, padding: '3px 12px', borderRadius: 999,
                            background: 'rgba(99,102,241,0.15)', color: 'var(--accent)',
                            border: '1px solid rgba(99,102,241,0.3)',
                          }}>
                            {selectedTemplate}
                          </span>
                          {templateConf != null && <ConfidenceBadge confidence={templateConf} />}
                        </div>
                        {templateReasoning && (
                          <div style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                            💡 {templateReasoning}
                          </div>
                        )}
                      </div>
                    )}

                    <div style={{
                      fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.6,
                      background: 'rgba(0,0,0,0.2)', padding: '8px 12px', borderRadius: 6,
                      borderLeft: '2px solid var(--accent)', marginBottom: 8,
                    }}>
                      💭 {d.reasoning || 'No reasoning provided'}
                    </div>

                    <div style={{ display: 'flex', gap: 16, fontSize: 12, color: 'var(--text-muted)' }}>
                      <span>Cycle: {d.cycle_id?.slice(0, 8)}…</span>
                      <span>{timeAgo(d.created_at)}</span>
                      {d.executed_at && <span>Executed: {fmtDate(d.executed_at)}</span>}
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexShrink: 0 }}>
                    {isPending && (
                      <button
                        className="btn btn-green"
                        style={{ fontSize: 12, padding: '6px 14px' }}
                        onClick={() => onApprove(d.id)}
                      >
                        ✓ Approve
                      </button>
                    )}
                    <button
                      className="btn btn-ghost"
                      style={{ fontSize: 12, padding: '6px 12px' }}
                      onClick={() => setExpanded(isExpanded ? null : d.id)}
                    >
                      {isExpanded ? '▲' : '▼'}
                    </button>
                  </div>
                </div>

                {isExpanded && d.outcome && (
                  <div style={{ marginTop: 12, padding: '12px', background: '#0d1117', borderRadius: 6, border: '1px solid var(--border)' }}>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 6 }}>Outcome</div>
                    <pre style={{ fontSize: 12, color: 'var(--cyan)', whiteSpace: 'pre-wrap', margin: 0 }}>
                      {JSON.stringify(outcomeObj, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Tab 3: Agent Memory ────────────────────────────────────────────────────────
function MemoryTab({ reflections, onRefresh, loading }: {
  reflections: AgentReflection[]; onRefresh: () => void; loading: boolean;
}) {
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h3 style={{ fontSize: 18, fontWeight: 600 }}>Agent Memory</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
            Distilled lessons the agent carries forward — not just a history log, actual standing opinions that shape future template and strategy decisions.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={onRefresh} disabled={loading}>↻ Refresh</button>
      </div>

      {loading ? <Spinner /> : reflections.length === 0 ? (
        <div className="empty-state">No reflections yet. The agent writes these after each cycle.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {reflections.map(r => (
            <div key={r.id} style={{
              background: 'rgba(139,92,246,0.06)', border: '1px solid rgba(139,92,246,0.2)',
              borderRadius: 12, padding: '18px 20px', borderLeft: '3px solid #8b5cf6',
            }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                    <span style={{ fontSize: 16 }}>🧠</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#a78bfa', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Lesson #{r.id}</span>
                    {r.tags?.template_name && (
                      <span style={{
                        fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 999,
                        background: 'rgba(99,102,241,0.2)', color: 'var(--accent)',
                      }}>
                        📋 {r.tags.template_name}
                      </span>
                    )}
                  </div>
                  <p style={{ fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.6, margin: 0 }}>
                    {r.lesson}
                  </p>

                  {r.tags && Object.keys(r.tags).length > 0 && (
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                      {Object.entries(r.tags).filter(([, v]) => v != null).map(([k, v]) => (
                        <span key={k} style={{
                          padding: '2px 8px', borderRadius: 999, fontSize: 11, fontWeight: 600,
                          background: 'rgba(139,92,246,0.15)', color: '#a78bfa',
                        }}>
                          {k}: {String(v)}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', flexShrink: 0 }}>
                  {timeAgo(r.created_at)}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Tab 4: Template Analytics ──────────────────────────────────────────────────
interface TemplateAnalytic {
  template_name: string;
  template_id: number | null;
  total_sent: number;
  open_rate: number;
  reply_rate: number;
  total_meetings: number;
  last_used: string | null;
  ai_recommendation: string;
}

function TemplateAnalyticsTab({ onRefresh, loading }: { onRefresh: () => void; loading: boolean }) {
  const [analytics, setAnalytics] = useState<TemplateAnalytic[]>([]);
  const [analyticsLoading, setAnalyticsLoading] = useState(true);

  const load = useCallback(async () => {
    setAnalyticsLoading(true);
    const data = await fetchJSON<TemplateAnalytic[]>('/orchestration/agent/template-analytics');
    if (data) setAnalytics(data);
    setAnalyticsLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const getRecommendationColor = (rec: string) => {
    if (rec.includes('Highly')) return 'var(--green)';
    if (rec.includes('Recommended')) return 'var(--cyan)';
    if (rec.includes('Low')) return 'var(--red)';
    return 'var(--text-muted)';
  };

  const getRecommendationIcon = (rec: string) => {
    if (rec.includes('Highly')) return '🏆';
    if (rec.includes('Recommended')) return '✅';
    if (rec.includes('Low')) return '⚠️';
    if (rec.includes('Not yet')) return '🔬';
    return '📊';
  };

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <div>
          <h3 style={{ fontSize: 18, fontWeight: 600 }}>Template Analytics</h3>
          <p style={{ color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
            Per-template campaign performance — the data the agent uses to select the best template. Computed from your outreach history.
          </p>
        </div>
        <button className="btn btn-ghost" onClick={load} disabled={analyticsLoading}>↻ Refresh</button>
      </div>

      {analyticsLoading ? <Spinner /> : analytics.length === 0 ? (
        <div className="empty-state">No template data yet. The agent will populate this after the first outreach cycle.</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
          {analytics.map(t => {
            const recColor = getRecommendationColor(t.ai_recommendation);
            const recIcon = getRecommendationIcon(t.ai_recommendation);
            const isHighlighted = t.ai_recommendation.includes('Highly');
            return (
              <div key={t.template_name} style={{
                background: isHighlighted ? 'rgba(34,197,94,0.04)' : 'var(--bg-card)',
                border: `1px solid ${isHighlighted ? 'rgba(34,197,94,0.25)' : 'var(--border)'}`,
                borderRadius: 14, padding: '20px 22px',
                boxShadow: isHighlighted ? '0 0 20px rgba(34,197,94,0.06)' : undefined,
                transition: 'all 0.2s',
              }}>
                {/* Header */}
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 4 }}>
                      {t.template_name}
                    </div>
                    {t.last_used ? (
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Last used {timeAgo(t.last_used)}</div>
                    ) : (
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Never used</div>
                    )}
                  </div>
                  {isHighlighted && (
                    <span style={{
                      fontSize: 11, fontWeight: 700, padding: '3px 9px', borderRadius: 999,
                      background: 'rgba(34,197,94,0.15)', color: 'var(--green)',
                      border: '1px solid rgba(34,197,94,0.3)',
                    }}>
                      🏆 Top Performer
                    </span>
                  )}
                </div>

                {/* Stats Grid */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginBottom: 16 }}>
                  <div style={{ textAlign: 'center', padding: '10px 8px', background: 'var(--bg-card-hover)', borderRadius: 8 }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-primary)' }}>{t.total_sent}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>Emails Sent</div>
                  </div>
                  <div style={{ textAlign: 'center', padding: '10px 8px', background: 'var(--bg-card-hover)', borderRadius: 8 }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: t.reply_rate >= 0.15 ? 'var(--green)' : t.reply_rate >= 0.05 ? 'var(--amber)' : 'var(--text-primary)' }}>
                      {t.total_sent > 0 ? `${(t.reply_rate * 100).toFixed(0)}%` : '—'}
                    </div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>Reply Rate</div>
                  </div>
                  <div style={{ textAlign: 'center', padding: '10px 8px', background: 'var(--bg-card-hover)', borderRadius: 8 }}>
                    <div style={{ fontSize: 20, fontWeight: 800, color: t.total_meetings > 0 ? 'var(--cyan)' : 'var(--text-primary)' }}>{t.total_meetings}</div>
                    <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 2 }}>Meetings</div>
                  </div>
                </div>

                {/* Reply rate bar */}
                {t.total_sent > 0 && (
                  <div style={{ marginBottom: 14 }}>
                    <div style={{ height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden' }}>
                      <div style={{
                        height: '100%',
                        width: `${Math.min(t.reply_rate * 100 * 4, 100)}%`,  // scale up for visibility
                        background: t.reply_rate >= 0.15 ? 'var(--green)' : t.reply_rate >= 0.05 ? 'var(--amber)' : 'var(--red)',
                        borderRadius: 2, transition: 'width 0.6s ease',
                      }} />
                    </div>
                  </div>
                )}

                {/* AI Recommendation */}
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px',
                  background: `${recColor}10`, borderRadius: 8, border: `1px solid ${recColor}25`,
                }}>
                  <span style={{ fontSize: 14 }}>{recIcon}</span>
                  <span style={{ fontSize: 12, fontWeight: 600, color: recColor }}>
                    {t.ai_recommendation}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Tab 5: Settings ────────────────────────────────────────────────────────────
function SettingsTab({ settings, templates, goal, onUpdate, onGoalSave }: {
  settings: any; templates: any[]; goal: AgentGoal | null;
  onUpdate: (u: any) => Promise<void>; onGoalSave: (g: Partial<AgentGoal>) => Promise<void>;
}) {
  const [draft, setDraft] = useState<any>(settings || {});
  const [strategy, setStrategy] = useState<OutreachStrategy>((goal?.outreach_strategy as OutreachStrategy) || 'fixed');
  const [savingConfig, setSavingConfig] = useState(false);
  const [savingStrategy, setSavingStrategy] = useState(false);

  useEffect(() => { if (settings) setDraft(settings); }, [settings]);
  useEffect(() => { if (goal?.outreach_strategy) setStrategy(goal.outreach_strategy as OutreachStrategy); }, [goal]);

  if (!settings) return <Spinner />;

  const handleSaveConfig = async () => {
    setSavingConfig(true);
    await onUpdate(draft);
    setTimeout(() => setSavingConfig(false), 1000);
  };

  const handleSaveStrategy = async () => {
    setSavingStrategy(true);
    await onGoalSave({ outreach_strategy: strategy } as any);
    setTimeout(() => setSavingStrategy(false), 1000);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      <div className="agent-control-layout">
        {/* LEFT: Agent Configuration */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <h3 className="card-title">⚙️ Agent Configuration</h3>

          <div className="form-group">
            <label className="form-label">Default Template (used when Fixed strategy is active)</label>
            <select
              value={draft.default_outreach_template_id || ''}
              onChange={e => setDraft((d: any) => ({ ...d, default_outreach_template_id: e.target.value ? parseInt(e.target.value) : null }))}
            >
              <option value="">-- None (AI generates freely) --</option>
              {templates.map(t => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label className="form-label">Run Interval (minutes)</label>
            <input type="number" value={draft.interval_minutes || 10}
              onChange={e => setDraft((d: any) => ({ ...d, interval_minutes: parseInt(e.target.value) || 10 }))} />
          </div>

          <div className="form-group">
            <label className="form-label">Max Leads per Run</label>
            <input type="number" value={draft.max_leads_per_run || 10}
              onChange={e => setDraft((d: any) => ({ ...d, max_leads_per_run: parseInt(e.target.value) || 10 }))} />
          </div>

          <div className="form-group">
            <label className="form-label">Daily Email Limit</label>
            <input type="number" value={draft.daily_email_limit || 50}
              onChange={e => setDraft((d: any) => ({ ...d, daily_email_limit: parseInt(e.target.value) || 50 }))} />
          </div>

          <div className="form-group">
            <label className="form-label">Outreach Emails per Cycle</label>
            <input type="number" min={1} max={20} value={draft.max_outreach_per_cycle || 3}
              onChange={e => setDraft((d: any) => ({ ...d, max_outreach_per_cycle: parseInt(e.target.value) || 3 }))} />
            <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4 }}>How many leads the agent emails per run</div>
          </div>

          <label className="checkbox-label" style={{ marginTop: 8 }}>
            <input type="checkbox" checked={draft.auto_send_emails || false}
              onChange={e => setDraft((d: any) => ({ ...d, auto_send_emails: e.target.checked }))} />
            <span>Auto-Send Emails (Bypass Manual Review)</span>
          </label>

          <label className="checkbox-label">
            <input type="checkbox" checked={draft.reply_monitoring || false}
              onChange={e => setDraft((d: any) => ({ ...d, reply_monitoring: e.target.checked }))} />
            <span>Enable Reply Monitoring</span>
          </label>
          
          <button className="btn btn-primary" style={{ width: '100%', marginTop: 12 }} onClick={handleSaveConfig} disabled={savingConfig}>
            {savingConfig ? 'Saved!' : 'Save Configuration'}
          </button>
        </div>

        {/* RIGHT: Outreach Strategy */}
        <div className="card" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div>
            <h3 className="card-title" style={{ marginBottom: 4 }}>🎯 Outreach Strategy</h3>
            <p style={{ fontSize: 13, color: 'var(--text-muted)', lineHeight: 1.5, marginBottom: 16 }}>
              Choose how the Agent Controller selects outreach templates for each cycle.
            </p>
          </div>

          <OutreachStrategySelector
            value={strategy}
            onChange={setStrategy}
          />

          {/* Contextual hint for AI select */}
          {strategy === 'ai_select' && (
            <div style={{
              padding: '12px 14px', borderRadius: 8,
              background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
              fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6,
            }}>
              <strong style={{ color: 'var(--accent)' }}>How it works:</strong>
              {' '}The controller reads your current goal, past campaign performance from email history,
              and lessons from Agent Memory, then calls the AI to pick the single best template.
              The reasoning and confidence score appear in the Decision Log.
            </div>
          )}

          {strategy === 'fixed' && (
            <div style={{
              padding: '12px 14px', borderRadius: 8,
              background: 'rgba(6,182,212,0.08)', border: '1px solid rgba(6,182,212,0.2)',
              fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6,
            }}>
              <strong style={{ color: 'var(--cyan)' }}>Tip:</strong>
              {' '}Set the "Default Template" in Agent Configuration above. If none is set, the AI generates content freely.
            </div>
          )}

          {strategy === 'rotate' && (
            <div style={{
              padding: '12px 14px', borderRadius: 8,
              background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.2)',
              fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6,
            }}>
              <strong style={{ color: 'var(--amber)' }}>How it works:</strong>
              {' '}Templates rotate sequentially based on total emails sent in the current period.
              Great for consistent A/B testing across your template library.
            </div>
          )}

          <div style={{ flex: 1 }} />
          
          <button
            className="btn btn-primary"
            style={{ width: '100%' }}
            onClick={handleSaveStrategy}
            disabled={savingStrategy}
          >
            {savingStrategy ? '✓ Strategy Saved!' : 'Save Outreach Strategy'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main AgentControlPage ──────────────────────────────────────────────────────
type Tab = 'status' | 'decisions' | 'memory' | 'analytics' | 'settings' | 'knowledge';

export default function AgentControlPage() {
  const [tab, setTab] = useState<Tab>('status');
  const [settings, setSettings] = useState<any>(null);
  const [goal, setGoal] = useState<AgentGoal | null>(null);
  const [decisions, setDecisions] = useState<AgentDecision[]>([]);
  const [reflections, setReflections] = useState<AgentReflection[]>([]);
  const [outreachTemplates, setOutreachTemplates] = useState<any[]>([]);
  const [systemLogs, setSystemLogs] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [decisionsLoading, setDecisionsLoading] = useState(false);
  const [memoryLoading, setMemoryLoading] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const initialLoadDone = React.useRef(false);

  // ── Full initial load: shows the page-level spinner only once ─────────────
  const loadBase = useCallback(async () => {
    if (!initialLoadDone.current) setLoading(true);
    const [s, g, sl] = await Promise.all([
      fetchJSON<any>('/orchestration/settings'),
      fetchJSON<AgentGoal>('/orchestration/agent/goal'),
      fetchJSON<{logs: string[]}>('/orchestration/agent/logs'),
    ]);
    const ot = await fetchJSON<any[]>('/outreach/templates').catch(() => null);
    if (s) setSettings(s);
    if (g) setGoal(g);
    if (sl) setSystemLogs(sl.logs || []);
    if (ot) setOutreachTemplates(ot);
    
    if (!initialLoadDone.current) {
      setLoading(false);
      initialLoadDone.current = true;
    }
  }, []);

  // ── Silent background refresh: no spinner, just updates data in-place ───
  const refreshBase = useCallback(async () => {
    const [s, g, sl] = await Promise.all([
      fetchJSON<any>('/orchestration/settings'),
      fetchJSON<AgentGoal>('/orchestration/agent/goal'),
      fetchJSON<{logs: string[]}>('/orchestration/agent/logs'),
    ]);
    if (s) setSettings(s);
    if (g) setGoal(g);
    if (sl) setSystemLogs(sl.logs || []);
  }, []);

  const loadDecisions = useCallback(async () => {
    setDecisionsLoading(true);
    const d = await fetchJSON<AgentDecision[]>('/orchestration/agent/decisions?limit=30');
    if (d) {
      setDecisions(d);
      setPendingCount(d.filter(x => x.status === 'pending_approval').length);
    }
    setDecisionsLoading(false);
  }, []);

  const loadMemory = useCallback(async () => {
    setMemoryLoading(true);
    const r = await fetchJSON<AgentReflection[]>('/orchestration/agent/reflections?limit=15');
    if (r) setReflections(r);
    setMemoryLoading(false);
  }, []);

  useEffect(() => { loadBase(); }, [loadBase]);
  useEffect(() => { if (tab === 'decisions') loadDecisions(); }, [tab, loadDecisions]);
  useEffect(() => { if (tab === 'memory') loadMemory(); }, [tab, loadMemory]);

  // Background polling — silent refreshes, no spinner
  // Status tab: refresh every 60s (agent cycles run every ~60s anyway)
  // Decision tab: refresh every 30s to catch new decisions
  useEffect(() => {
    if (tab === 'decisions') {
      const interval = setInterval(async () => {
        // Silent decision refresh (no loading spinner)
        const d = await fetchJSON<AgentDecision[]>('/orchestration/agent/decisions?limit=30');
        if (d) {
          setDecisions(d);
          setPendingCount(d.filter(x => x.status === 'pending_approval').length);
        }
      }, 30000);
      return () => clearInterval(interval);
    } else if (tab === 'status') {
      const interval = setInterval(refreshBase, 60000); // silent, no spinner
      return () => clearInterval(interval);
    }
  }, [tab, refreshBase]);

  const handleGoalSave = async (updates: Partial<AgentGoal>) => {
    await postJSON('/orchestration/agent/goal', updates);
    const g = await fetchJSON<AgentGoal>('/orchestration/agent/goal');
    if (g) setGoal(g);
  };

  const handleSettingsUpdate = async (updates: any) => {
    const newSettings = { ...settings, ...updates };
    setSettings(newSettings);
    await postJSON('/orchestration/settings', newSettings);
    loadBase();
  };

  const handleApprove = async (id: number) => {
    await postJSON(`/orchestration/agent/decisions/${id}/approve`);
    loadDecisions();
  };

  const tabDefs: { key: Tab; label: string; badge?: number }[] = [
    { key: 'status',    label: '🎯 Status & Goal' },
    { key: 'decisions', label: '🧠 Decision Log', badge: pendingCount || undefined },
    { key: 'memory',    label: '💡 Agent Memory' },
    { key: 'analytics', label: '📊 Template Analytics' },
    { key: 'knowledge', label: '🌐 Knowledge Base' },
    { key: 'settings',  label: '⚙️ Settings' },
  ];

  return (
    <div className="page-container">
      <div className="page-header">
        <div>
          <h1 className="page-title">🤖 Agent Control</h1>
          <p className="page-subtitle">
            Goal-directed autonomous agent — perceives state, decides, acts, and learns from outcomes.
          </p>
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          {pendingCount > 0 && (
            <div style={{
              padding: '6px 14px', borderRadius: 999, fontSize: 13, fontWeight: 700,
              background: 'rgba(245,158,11,0.15)', color: 'var(--amber)', border: '1px solid rgba(245,158,11,0.3)',
            }}>
              ⏳ {pendingCount} awaiting approval
            </div>
          )}
          <div style={{ fontSize: 14, fontWeight: 600, color: settings?.enabled ? 'var(--green)' : 'var(--text-muted)' }}>
            {settings?.enabled ? '● AGENT ACTIVE' : '○ AGENT OFF'}
          </div>
          <button className="btn btn-ghost" onClick={() => { loadBase(); if (tab === 'decisions') loadDecisions(); }}>
            ↻ Refresh
          </button>
        </div>
      </div>

      {/* Tab Bar */}
      <div className="tab-bar" style={{ marginBottom: 28 }}>
        {tabDefs.map(t => (
          <div key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
            {t.label}
            {t.badge && (
              <span style={{
                marginLeft: 6, padding: '1px 7px', borderRadius: 999, fontSize: 11,
                fontWeight: 700, background: 'rgba(245,158,11,0.2)', color: 'var(--amber)',
              }}>
                {t.badge}
              </span>
            )}
          </div>
        ))}
      </div>

      {loading ? <Spinner /> : (
        <>
          {tab === 'status' && (
            <StatusGoalTab
              settings={settings}
              goal={goal}
              systemLogs={systemLogs}
              onGoalSave={handleGoalSave}
              onSettingsUpdate={handleSettingsUpdate}
            />
          )}
          {tab === 'decisions' && (
            <DecisionLogTab
              decisions={decisions}
              onApprove={handleApprove}
              onRefresh={loadDecisions}
              loading={decisionsLoading}
            />
          )}
          {tab === 'memory' && (
            <MemoryTab
              reflections={reflections}
              onRefresh={loadMemory}
              loading={memoryLoading}
            />
          )}
          {tab === 'analytics' && (
            <TemplateAnalyticsTab
              onRefresh={() => {}}
              loading={false}
            />
          )}
          {tab === 'knowledge' && (
            <KnowledgeTab />
          )}
          {tab === 'settings' && (
            <SettingsTab
              settings={settings}
              templates={outreachTemplates}
              goal={goal}
              onUpdate={handleSettingsUpdate}
              onGoalSave={handleGoalSave}
            />
          )}
        </>
      )}
    </div>
  );
}
