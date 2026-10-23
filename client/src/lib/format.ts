import { formatDistanceToNowStrict } from 'date-fns';

/** API timestamps are naive UTC (no offset); parse them as UTC. */
export function parseApiDate(value: string | null | undefined): Date | null {
  if (!value) return null;
  const hasZone = /[zZ]|[+-]\d\d:?\d\d$/.test(value);
  const d = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function ago(value: string | null | undefined, never = 'never'): string {
  const d = parseApiDate(value);
  return d ? `${formatDistanceToNowStrict(d)} ago` : never;
}

export function dateTime(value: string | null | undefined, empty = '—'): string {
  const d = parseApiDate(value);
  return d ? d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : empty;
}

export function mb(value: number | null | undefined): string {
  if (value == null) return '—';
  return value >= 1024 ? `${(value / 1024).toFixed(value % 1024 === 0 ? 0 : 1)} GB` : `${value} MB`;
}

export function bytes(value: number | null | undefined): string {
  if (value == null) return '—';
  return mb(Math.round(value / 2 ** 20));
}

export function count(value: number | null | undefined): string {
  return value == null ? '—' : value.toLocaleString();
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : '—';
}

/** Display default; amounts from the API carry their own currency, which callers pass when they have it. */
export const BILLING_CURRENCY = process.env.NEXT_PUBLIC_BILLING_CURRENCY || 'NGN';

/** Ledger amounts arrive as decimal strings. */
export function money(value: string | number | null | undefined, currency = BILLING_CURRENCY): string {
  const n = typeof value === 'string' ? Number(value) : (value ?? 0);
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, maximumFractionDigits: 4 }).format(n);
}

export const RUNTIME_LABEL: Record<string, string> = { ollama: 'Ollama', llamacpp: 'llama.cpp', vllm: 'vLLM' };

export function runtimeLabel(runtime: string | null | undefined): string {
  return runtime ? (RUNTIME_LABEL[runtime] ?? runtime) : '—';
}
