import React, { useState, useEffect, useCallback } from 'react';
import { fetchJSON, postJSON, fmtDate, timeAgo } from '../../utils/api';
import { Spinner } from '../../components/common/Shared';

export default function KnowledgeTab() {
  const [knowledge, setKnowledge] = useState<any>(null);
  const [logs, setLogs] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [kb, logData] = await Promise.all([
        fetchJSON<any>('/knowledge/current'),
        fetchJSON<any[]>('/knowledge/logs')
      ]);
      if (kb) setKnowledge(kb);
      if (logData) setLogs(logData);
    } catch (e) {
      console.error("Failed to load knowledge base data", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    // Poll logs occasionally if currently syncing
    const interval = setInterval(() => {
      fetchJSON<any[]>('/knowledge/logs').then(logData => {
        if (logData) {
          setLogs(logData);
          if (logData[0]?.status !== 'running') {
            setSyncing(false);
          }
        }
      });
    }, 10000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await postJSON('/knowledge/sync', {});
      loadData();
    } catch (e) {
      console.error(e);
      setSyncing(false);
    }
  };

  if (loading) return <Spinner />;

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 340px', gap: 24 }}>
      {/* LEFT: Knowledge Base Content */}
      <div className="card">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 18 }}>SETV Knowledge Base</h2>
            <p style={{ margin: 0, color: 'var(--text-muted)', fontSize: 13, marginTop: 4 }}>
              Structured business intelligence automatically synchronized from setvglobal.com.
            </p>
          </div>
          <button 
            className="btn btn-primary" 
            onClick={handleSync} 
            disabled={syncing || (logs[0]?.status === 'running')}
          >
            {syncing || logs[0]?.status === 'running' ? '⏳ Syncing...' : '🔄 Sync Now'}
          </button>
        </div>

        {knowledge?.data ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            {Object.entries(knowledge.data).map(([key, items]: [string, any]) => {
              if (!Array.isArray(items) || items.length === 0) return null;
              // Format key name nicely
              const title = key.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
              return (
                <div key={key}>
                  <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--accent)', marginBottom: 8, borderBottom: '1px solid var(--border)', paddingBottom: 4 }}>
                    {title}
                  </h4>
                  <ul style={{ margin: 0, paddingLeft: 20, fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.6 }}>
                    {items.map((item, idx) => (
                      <li key={idx} style={{ marginBottom: 4 }}>{item}</li>
                    ))}
                  </ul>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="empty-state">No knowledge base data available. Click "Sync Now" to crawl the website.</div>
        )}
      </div>

      {/* RIGHT: Sync History */}
      <div className="card">
        <h3 style={{ margin: 0, fontSize: 16, marginBottom: 16 }}>Sync History</h3>
        {logs.length === 0 ? (
          <div className="empty-state" style={{ padding: '20px' }}>No sync history.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {logs.map((log) => (
              <div key={log.id} style={{
                background: 'var(--bg-card-hover)', padding: '12px 16px', borderRadius: 10,
                borderLeft: `4px solid ${
                  log.status === 'success' ? 'var(--green)' :
                  log.status === 'running' ? 'var(--amber)' : 'var(--red)'
                }`
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 700 }}>
                    {log.status === 'success' ? '✅ Completed' : log.status === 'running' ? '⏳ Running...' : '❌ Failed'}
                  </span>
                  <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{timeAgo(log.sync_time)}</span>
                </div>
                {log.knowledge_version && (
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                    Version: <b>v{log.knowledge_version}</b>
                  </div>
                )}
                {log.changes_detected?.summary && log.changes_detected.summary.length > 50 && (
                   <div style={{ fontSize: 12, marginTop: 8, padding: 8, background: 'rgba(0,0,0,0.2)', borderRadius: 6, maxHeight: 100, overflowY: 'auto' }}>
                     {log.changes_detected.summary}
                   </div>
                )}
                {log.errors && (
                  <div style={{ fontSize: 12, color: 'var(--red)', marginTop: 8, wordBreak: 'break-word' }}>
                    {log.errors}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
