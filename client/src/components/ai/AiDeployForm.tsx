'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Notice, TrustNotice } from '@/components/common/Notices';
import { useCreateAiRun } from '@/hooks/useAiDeployments';
import { DEFAULT_LIMITS, MAX_DURATION_HOURS, MAX_RECOVERY_ATTEMPTS, MAX_REQUEST_CHARS, validateAiRequest } from '@/lib/ai';
import { RUNTIME_PREFERENCE, newIdempotencyKey } from '@/lib/deployments';
import { errorMessage } from '@/lib/errors';
import { BILLING_CURRENCY, runtimeLabel } from '@/lib/format';
import type { AutonomyLimits, ModelSource, Runtime } from '@/types';

const SOURCES: { id: ModelSource; label: string }[] = [
  { id: 'ollama', label: 'Ollama registry' },
  { id: 'huggingface', label: 'Hugging Face (pinned revisions)' },
];

function toggle<T>(list: T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

export function AiDeployForm() {
  const router = useRouter();
  const create = useCreateAiRun();
  const [text, setText] = useState('');
  const [limits, setLimits] = useState<AutonomyLimits>(DEFAULT_LIMITS);
  const [acknowledged, setAcknowledged] = useState(false);
  const [touched, setTouched] = useState(false);
  // One key per form instance: a double submit returns the same run.
  const [idempotencyKey] = useState(newIdempotencyKey);
  const problems = validateAiRequest(text, limits);
  const set = <K extends keyof AutonomyLimits>(key: K, value: AutonomyLimits[K]) => setLimits((l) => ({ ...l, [key]: value }));
  const num = (v: string) => (v === '' ? NaN : Number(v));

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    setTouched(true);
    if (problems.length || !acknowledged) return;
    create.mutate(
      { request: text.trim(), limits, idempotency_key: idempotencyKey },
      { onSuccess: (run) => router.push(`/customer/ai/${run.id}`) },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-6" noValidate>
      <div className="space-y-2">
        <Label htmlFor="ai-request">What should be deployed?</Label>
        <Textarea
          id="ai-request"
          value={text}
          maxLength={MAX_REQUEST_CHARS}
          onChange={(e) => setText(e.target.value)}
          placeholder="A small, fast chat model for answering customer questions in English. Keep it cheap; no GPU."
          className="min-h-24"
        />
        <p className="text-xs text-muted-foreground">
          The AI agent picks a model from the approved catalog. It cannot exceed the limits below: AgentMesh checks every
          plan against them, your wallet, and current prices before anything runs.
        </p>
      </div>

      <fieldset className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <legend className="mb-2 text-sm font-medium">Limits you authorize</legend>
        <NumberField
          id="max-spend"
          label={`Maximum spend (${BILLING_CURRENCY})`}
          value={limits.max_spend}
          onChange={(v) => set('max_spend', v)}
          hint="Stopped automatically when reached"
        />
        <NumberField
          id="max-hours"
          label="Maximum duration (hours)"
          value={String(limits.max_duration_hours)}
          onChange={(v) => set('max_duration_hours', num(v))}
          hint={`Up to ${MAX_DURATION_HOURS} h`}
        />
        <NumberField
          id="max-recovery"
          label="Automatic recovery attempts"
          value={String(limits.max_recovery_attempts)}
          onChange={(v) => set('max_recovery_attempts', num(v))}
          hint={`0-${MAX_RECOVERY_ATTEMPTS}`}
        />
        <NumberField id="max-cpu" label="Maximum CPU cores" value={String(limits.max_cpu_cores)} onChange={(v) => set('max_cpu_cores', num(v))} />
        <NumberField id="max-ram" label="Maximum memory (MB)" value={String(limits.max_ram_mb)} onChange={(v) => set('max_ram_mb', num(v))} />
        <NumberField
          id="max-vram"
          label="Maximum GPU memory (MB)"
          value={String(limits.max_vram_mb)}
          onChange={(v) => set('max_vram_mb', num(v))}
          hint="0 means no GPU"
        />
      </fieldset>

      <div className="grid gap-4 sm:grid-cols-2">
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Allowed runtimes</legend>
          {RUNTIME_PREFERENCE.map((r: Runtime) => (
            <label key={r} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={limits.allowed_runtimes.includes(r)}
                onChange={() => set('allowed_runtimes', toggle(limits.allowed_runtimes, r))}
              />
              {runtimeLabel(r)}
            </label>
          ))}
        </fieldset>
        <fieldset className="space-y-2">
          <legend className="text-sm font-medium">Allowed model sources</legend>
          {SOURCES.map((s) => (
            <label key={s.id} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={limits.allowed_sources.includes(s.id)}
                onChange={() => set('allowed_sources', toggle(limits.allowed_sources, s.id))}
              />
              {s.label}
            </label>
          ))}
        </fieldset>
      </div>

      <TrustNotice />
      <label className="flex items-start gap-2 text-sm">
        <input type="checkbox" className="mt-0.5" checked={acknowledged} onChange={(e) => setAcknowledged(e.target.checked)} />
        <span>I understand, and I authorize the agent to deploy and spend within these limits without asking again.</span>
      </label>

      {touched && problems.length > 0 && (
        <Notice tone="warning" title="Check the form">
          <ul className="list-disc pl-4">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Notice>
      )}
      {create.error && <Notice tone="danger">{errorMessage(create.error)}</Notice>}

      <Button type="submit" disabled={create.isPending || !acknowledged}>
        {create.isPending ? 'Starting…' : 'Start autonomous deployment'}
      </Button>
    </form>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
  hint,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input id={id} inputMode="decimal" value={Number.isNaN(Number(value)) ? '' : value} onChange={(e) => onChange(e.target.value)} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}
