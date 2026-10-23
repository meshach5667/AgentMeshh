'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { CodeBlock, InlineValue } from '@/components/common/CodeBlock';
import { Notice, PageHeader } from '@/components/common/Notices';
import { useCreateEnrollmentToken } from '@/hooks/useNodes';
import { useWorkerRelease } from '@/hooks/useWorkerRelease';
import { RELEASES_URL, WORKER_VERSION } from '@/lib/config';
import { agentInstallCommand, dockerInstallCommand, sourceInstallCommand, statusCommand, uninstallCommand, workerReleaseUrl } from '@/lib/worker';
import { errorMessage } from '@/lib/errors';
import { dateTime } from '@/lib/format';

export default function EnrollNodePage() {
  const create = useCreateEnrollmentToken();
  const [name, setName] = useState('');
  const [region, setRegion] = useState('');
  const [mode, setMode] = useState<'agent' | 'docker'>('agent');
  const token = create.data?.token;

  const release = useWorkerRelease();
  const published = release.data === 'published';

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <PageHeader title="Add a machine" description="Enroll a computer as an AgentMesh node. The worker only makes outbound connections; you do not need to open any ports." />

      <Card>
        <CardHeader>
          <CardTitle>1. Create a one-time enrollment token</CardTitle>
          <CardDescription>The token works once and expires after 60 minutes. Create a new one for each machine.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="grid gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end"
            onSubmit={(e) => {
              e.preventDefault();
              create.mutate({ name: name.trim() || undefined, region: region.trim() || undefined });
            }}
          >
            <div className="space-y-2">
              <Label htmlFor="node-name">Name (optional)</Label>
              <Input id="node-name" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} placeholder="office-desktop" />
            </div>
            <div className="space-y-2">
              <Label htmlFor="node-region">Region (optional)</Label>
              <Input id="node-region" maxLength={100} value={region} onChange={(e) => setRegion(e.target.value)} placeholder="eu-west" />
            </div>
            <Button type="submit" disabled={create.isPending}>
              {token ? 'Create another' : 'Create token'}
            </Button>
          </form>
          {create.error && <p className="mt-3 text-sm text-rose-500">{errorMessage(create.error)}</p>}
          {create.data && (
            <div className="mt-4 space-y-2">
              <InlineValue value={create.data.token} />
              <p className="text-xs text-muted-foreground">Expires {dateTime(create.data.expires_at)}. It is shown only now.</p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>2. Install the worker</CardTitle>
          <CardDescription>
            The limits you pass are the most AgentMesh will ever reserve on the machine. See the{' '}
            <Link href="/docs/providers" className="underline underline-offset-4">provider guide</Link> for every option.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div role="tablist" className="flex gap-1">
            {(['agent', 'docker'] as const).map((m) => (
              <button
                key={m}
                role="tab"
                type="button"
                aria-selected={mode === m}
                onClick={() => setMode(m)}
                className={`rounded-md px-3 py-1 text-sm ${mode === m ? 'bg-muted font-medium' : 'text-muted-foreground'}`}
              >
                {m === 'agent' ? 'Installable agent (Linux, macOS)' : 'Docker worker'}
              </button>
            ))}
          </div>
          {mode === 'agent' ? (
            <>
              <p className="text-sm text-muted-foreground">
                Linux or macOS with Python 3.11+ (including <code className="font-mono">venv</code>) and{' '}
                <a href="https://ollama.com/download" className="underline underline-offset-4" target="_blank" rel="noreferrer">Ollama</a>{' '}
                installed. No admin rights: it runs as a per-user service and starts its own isolated model servers, never
                touching your own Ollama service or models.
              </p>
              {release.isPending ? (
                <p className="text-sm text-muted-foreground">Checking for the worker {WORKER_VERSION} release…</p>
              ) : published ? (
                <>
                  <p className="text-sm text-muted-foreground">
                    Downloads the{' '}
                    <a href={workerReleaseUrl()} className="underline underline-offset-4" target="_blank" rel="noreferrer">
                      worker {WORKER_VERSION} release
                    </a>
                    , verifies it against <code className="font-mono">SHA256SUMS</code>, then installs. Your token is only
                    passed to the installer, never put in a URL.
                  </p>
                  <CodeBlock code={agentInstallCommand({ token })} />
                  <p className="text-xs text-muted-foreground">
                    Keep the <code className="font-mono">~/agentmesh-worker-{WORKER_VERSION}</code> folder: it holds the
                    uninstaller (<code className="font-mono">{uninstallCommand()}</code>).
                  </p>
                </>
              ) : (
                <>
                  <Notice tone="warning" title={`Worker ${WORKER_VERSION} has not been published yet`}>
                    Prebuilt downloads will appear on the{' '}
                    <a href={RELEASES_URL} className="underline underline-offset-4" target="_blank" rel="noreferrer">
                      GitHub Releases page
                    </a>
                    . Until then, build the worker from the source repository:
                  </Notice>
                  <CodeBlock code={sourceInstallCommand({ token })} />
                </>
              )}
            </>
          ) : (
            <>
              <p className="text-sm text-muted-foreground">
                Needs Docker Engine 24+ and the Compose file from the repository, so this option still uses a checkout.
              </p>
              <CodeBlock code={dockerInstallCommand({ token })} />
              <Notice tone="warning">
                The worker uses the Docker socket, which is equivalent to root access on the machine. Prefer rootless
                Docker and a machine dedicated to this purpose.
              </Notice>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>3. Check it appears</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            The machine shows up in{' '}
            <Link href="/provider/nodes" className="underline underline-offset-4">
              My nodes
            </Link>{' '}
            within a few seconds of enrolling. If it does not, check the worker on the machine (installable agent):
          </p>
          <CodeBlock code={statusCommand} />
          <p>
            Troubleshooting and service logs are covered in the{' '}
            <Link href="/docs/providers#troubleshooting" className="underline underline-offset-4">provider guide</Link>.
          </p>
        </CardContent>
      </Card>

      <Notice tone="info" title="What hosting means for you">
        AgentMesh runs open-weight models on your machine inside resource limits. You can pause, drain or remove the
        worker at any time. Requests and responses pass through your machine; do not use it to inspect customers&apos;
        data. You earn a share of what customers pay while your node serves their deployments, and withdraw it to a bank account from Earnings &amp; Payouts.
      </Notice>
    </div>
  );
}
