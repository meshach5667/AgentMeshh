'use client';

import Link from 'next/link';
import { useParams } from 'next/navigation';
import toast from 'react-hot-toast';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { AiHealthBadge } from '@/components/ai/AiHealthBadge';
import { AiRunTimeline } from '@/components/ai/AiRunTimeline';
import { InlineValue } from '@/components/common/CodeBlock';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { StatusBadge } from '@/components/common/StatusBadge';
import { ErrorState, Notice, PageHeader } from '@/components/common/Notices';
import { PageSkeleton } from '@/components/ui/Skeleton';
import { useAiRun, useAiRunEvents, useCancelAiRun } from '@/hooks/useAiDeployments';
import { AI_STATUS_HELP, STOP_REASON_TEXT } from '@/lib/ai';
import { errorMessage } from '@/lib/errors';
import { dateTime, money, runtimeLabel, shortId } from '@/lib/format';
import { AI_TERMINAL_STATUSES } from '@/types';

export default function AiRunPage() {
  const id = useParams<{ id: string }>().id;
  const { data: run, isLoading, error, refetch } = useAiRun(id);
  const live = !!run && !AI_TERMINAL_STATUSES.includes(run.status);
  const events = useAiRunEvents(id, live);
  const cancel = useCancelAiRun();

  if (isLoading) return <PageSkeleton />;
  if (error || !run) return <ErrorState message={errorMessage(error, 'AI deployment not found')} retry={() => refetch()} />;

  const currency = run.currency ?? undefined;
  const tone = run.status === 'FAILED' ? 'danger' : run.status === 'RECOVERING' || run.waiting_for_ai ? 'warning' : 'info';

  return (
    <div className="space-y-6">
      <PageHeader
        title={run.model_name ?? 'AI deployment'}
        description={run.request}
        actions={
          <>
            <AiHealthBadge />
            {live && run.status !== 'STOPPING' && (
              <ConfirmButton
                confirmLabel="Cancel and stop everything"
                onConfirm={() =>
                  cancel.mutateAsync(run.id).then(
                    () => toast.success('Cancellation requested'),
                    (e) => toast.error(errorMessage(e)),
                  )
                }
              >
                Cancel
              </ConfirmButton>
            )}
          </>
        }
      />

      <Card>
        <CardContent className="grid gap-4 pt-6 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Status">
            <StatusBadge status={run.status} />
          </Field>
          <Field label="Deployment">
            {run.deployment_id ? (
              <Link href={`/customer/deployments/${run.deployment_id}`} className="font-mono underline underline-offset-4">
                {shortId(run.deployment_id)}
              </Link>
            ) : (
              '—'
            )}
            {run.deployment_status && <span className="text-muted-foreground"> · {run.deployment_status}</span>}
          </Field>
          <Field label="Runtime">{runtimeLabel(run.runtime ?? run.plan?.runtime ?? null)}</Field>
          <Field label="Stops at">{dateTime(run.deadline_at, 'after submission')}</Field>
          <Field label="Estimated cost">
            {run.estimated_total ? (
              <>
                {money(run.estimated_total, currency)}
                <span className="text-muted-foreground"> ({money(run.estimated_hourly, currency)}/h)</span>
              </>
            ) : (
              '—'
            )}
          </Field>
          <Field label="Actual cost">
            <span data-testid="ai-actual-cost">{money(run.actual_cost, currency)}</span>
          </Field>
          <Field label="Authorized maximum">
            {money(run.limits.max_spend, currency)} · {run.limits.max_duration_hours} h
          </Field>
          <Field label="Recovery attempts">
            {run.recovery_attempts} of {run.limits.max_recovery_attempts}
          </Field>
        </CardContent>
      </Card>

      <Notice tone={tone} title={run.status}>
        {AI_STATUS_HELP[run.status]}
        {run.waiting_for_ai && (
          <span className="mt-1 block">
            Waiting for the AI service. If it is offline, this step waits until it reconnects or the request expires; nothing is
            decided without it.
          </span>
        )}
        {run.stop_reason && <span className="mt-1 block">{STOP_REASON_TEXT[run.stop_reason] ?? run.stop_reason}.</span>}
        {run.error_message && (
          <span className="mt-1 block">
            <span className="font-mono text-xs">{run.error_code}</span> {run.error_message}
          </span>
        )}
      </Notice>

      {run.explanation && (
        <Card>
          <CardHeader>
            <CardTitle>Agent&apos;s explanation</CardTitle>
            <CardDescription>Written by the AI model. Informational only: AgentMesh verified the facts shown above.</CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm whitespace-pre-wrap" data-testid="ai-explanation">
              {run.explanation}
            </p>
          </CardContent>
        </Card>
      )}

      {run.status === 'READY' && run.openai_base_url && (
        <Card>
          <CardHeader>
            <CardTitle>Verified endpoint</CardTitle>
            <CardDescription>
              Published after a real test request succeeded. Authenticate with an{' '}
              <Link href="/customer/api-keys" className="underline underline-offset-4">
                API key
              </Link>
              ; see the{' '}
              <Link href={`/customer/deployments/${run.deployment_id}`} className="underline underline-offset-4">
                deployment page
              </Link>{' '}
              for examples and a playground.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <InlineValue value={run.openai_base_url} />
          </CardContent>
        </Card>
      )}

      {run.plan && (
        <Card>
          <CardHeader>
            <CardTitle>Accepted plan</CardTitle>
            <CardDescription>Proposed by the agent and validated by AgentMesh against your limits.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Model">{run.model_name ?? shortId(run.plan.model_id)}</Field>
            <Field label="Runtime">{run.plan.runtime ? runtimeLabel(run.plan.runtime) : 'Any allowed'}</Field>
            <Field label="Context window">{run.plan.num_ctx.toLocaleString()} tokens</Field>
            <Field label="Duration">{run.plan.duration_hours} h</Field>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Progress</CardTitle>
          <CardDescription>
            {live ? 'Updating every few seconds.' : 'History.'} {run.agent_steps} AI steps, {run.tool_calls} tool calls.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {events.error ? <p className="text-sm text-rose-500">{errorMessage(events.error)}</p> : <AiRunTimeline events={events.data ?? []} />}
        </CardContent>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <div className="text-sm">{children}</div>
    </div>
  );
}
