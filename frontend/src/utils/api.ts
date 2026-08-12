export const API = import.meta.env.VITE_API_URL || 'http://localhost:8000';
import { Lead } from '../types';

interface CacheEntry {
  data: any;
  timestamp: number;
}

const cache: Record<string, CacheEntry> = {};
const CACHE_TTL = 30000; // 30 seconds cache TTL

const NO_CACHE_PATHS = [
  '/calendar/meetings',
  '/meetings',
  '/orchestration/agent/settings',
  '/agents/status',
  '/orchestration/agent/logs',
  '/knowledge/logs',
  '/prospecting/jobs',
  '/replies/inbox',
];

export function invalidateCache(pathPrefix?: string) {
  if (!pathPrefix) {
    for (const key in cache) {
      delete cache[key];
    }
  } else {
    for (const key in cache) {
      if (key.startsWith(pathPrefix)) {
        delete cache[key];
      }
    }
  }
}

export async function fetchJSON<T>(path: string): Promise<T | null> {
  const shouldCache = !NO_CACHE_PATHS.some(p => path.startsWith(p));
  
  if (shouldCache) {
    const cached = cache[path];
    const now = Date.now();
    if (cached && (now - cached.timestamp < CACHE_TTL)) {
      // Revalidate in background
      fetch(`${API}${path}`)
        .then(async res => {
          if (res.ok) {
            const data = await res.json();
            cache[path] = { data, timestamp: Date.now() };
          }
        })
        .catch(e => console.error(`Background refresh error: ${path}`, e));

      return cached.data as T;
    }
  }

  try {
    const res = await fetch(`${API}${path}`);
    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    if (shouldCache) {
      cache[path] = { data, timestamp: Date.now() };
    }
    return data;
  } catch (e) { console.error(`API error: ${path}`, e); return null; }
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T | null> {
  try {
    const res = await fetch(`${API}${path}`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: body ? JSON.stringify(body) : undefined });
    if (!res.ok) throw new Error(`${res.status}`);
    // Clear entire cache on any successful POST action because it changes database state
    invalidateCache();
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

