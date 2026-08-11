export const API = 'http://localhost:8000';
import { Lead } from '../types';
export async function fetchJSON<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (e) { console.error(`API error: ${path}`, e); return null; }
}
export async function postJSON<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) throw new Error(`${res.status}`);
    return await res.json();
  } catch (e) { console.error(`POST error: ${path}`, e); return null; }
}
export function timeAgo(dt?: string) {
  if (!dt) return '—';
  const d = new Date(dt.endsWith('Z') ? dt : dt + 'Z');
  const sec = Math.floor((Date.now() - d.getTime()) / 1000);
  if (sec < 60) return 'just now';
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h ago`;
  return `${Math.floor(sec / 86400)}d ago`;
}
export function fmtDate(dt?: string) {
  if (!dt) return '—';
  try { return new Date(dt.endsWith('Z') ? dt : dt + 'Z').toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }); } catch { return dt; }
}
export function getLeadDisplayName(lead: Lead) {
  if (lead.company_name && lead.contact_name) return `${lead.company_name} — ${lead.contact_name}`;
  if (lead.company_name) return lead.company_name;
  if (lead.contact_name) return lead.contact_name;
  return `Lead #${lead.id}`;
}

