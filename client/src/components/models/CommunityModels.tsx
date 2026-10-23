'use client';

import { useState } from 'react';
import Link from 'next/link';
import toast from 'react-hot-toast';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ConfirmButton } from '@/components/common/ConfirmButton';
import { Pill } from '@/components/common/StatusBadge';
import { Notice } from '@/components/common/Notices';
import {
  useCommunityModels,
  useImportCommunityModel,
  usePreviewCommunityModel,
  useWithdrawCommunityModel,
} from '@/hooks/useModels';
import { errorMessage } from '@/lib/errors';
import { bytes, mb } from '@/lib/format';
import type { CommunityModelPreview } from '@/types';

/** Import a public GGUF file from Hugging Face. Two steps: look the repository up, then pick a file and accept. */
function ImportForm() {
  const [repo, setRepo] = useState('');
  const [revision, setRevision] = useState('');
  const [file, setFile] = useState<string | null>(null);
  const [accepted, setAccepted] = useState(false);
  const [preview, setPreview] = useState<CommunityModelPreview | null>(null);
  const lookUp = usePreviewCommunityModel();
  const importModel = useImportCommunityModel();

  const onLookUp = (e: React.FormEvent) => {
    e.preventDefault();
    setPreview(null);
    setFile(null);
    setAccepted(false);
    lookUp
      .mutateAsync({ repo: repo.trim(), revision: revision.trim() })
      .then((p) => {
        setPreview(p);
        setFile(p.files.find((f) => !f.problem)?.name ?? null);
      })
      .catch((err) => toast.error(errorMessage(err)));
  };

  const onImport = () => {
    if (!preview || !file) return;
    importModel
      // Import the exact commit that was previewed, not whatever the branch points to by now.
      .mutateAsync({ repo: preview.repo, file, revision: preview.revision, accept_terms: accepted })
      .then((m) => {
        toast.success(`Imported ${m.name}`);
        setPreview(null);
        setRepo('');
        setRevision('');
      })
      .catch((err) => toast.error(errorMessage(err)));
  };

  return (
    <div className="space-y-4">
      <form onSubmit={onLookUp} className="grid gap-3 sm:grid-cols-[1fr_10rem_auto] sm:items-end">
        <div className="space-y-1">
          <Label htmlFor="hf-repo">Hugging Face repository or link</Label>
          <Input
            id="hf-repo"
            required
            placeholder="bartowski/SmolLM2-135M-Instruct-GGUF"
            value={repo}
            onChange={(e) => setRepo(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="hf-revision">Branch or commit</Label>
          <Input id="hf-revision" placeholder="main" value={revision} onChange={(e) => setRevision(e.target.value)} />
        </div>
        <Button type="submit" disabled={lookUp.isPending || !repo.trim()}>
          {lookUp.isPending ? 'Looking up…' : 'Look up'}
        </Button>
      </form>

      {preview && (
        <div className="space-y-3 rounded-md border border-border p-4 text-sm">
          <p>
            <span className="font-medium">{preview.repo}</span>{' '}
            <span className="font-mono text-xs text-muted-foreground">@ {preview.revision.slice(0, 12)}</span>
            <span className="block text-muted-foreground">
              {[preview.license && `License: ${preview.license}`, preview.architecture, preview.context_length && `${preview.context_length.toLocaleString()} token context`]
                .filter(Boolean)
                .join(' · ')}
            </span>
          </p>
          {preview.license_problem ? (
            <Notice tone="danger" title="Cannot be imported">
              {preview.license_problem}
            </Notice>
          ) : preview.files.length === 0 ? (
            <Notice tone="warning" title="No GGUF files">
              This repository has no .gguf files at its top level. Look for a repository that publishes GGUF quantizations.
            </Notice>
          ) : (
            <>
              <fieldset className="space-y-1">
                <legend className="mb-1 font-medium">Choose a file</legend>
                {preview.files.map((f) => (
                  <label
                    key={f.name}
                    className={`flex items-start gap-2 rounded px-2 py-1 ${f.problem ? 'text-muted-foreground' : 'cursor-pointer hover:bg-muted'}`}
                  >
                    <input
                      type="radio"
                      name="gguf-file"
                      className="mt-1"
                      disabled={!!f.problem}
                      checked={file === f.name}
                      onChange={() => setFile(f.name)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="break-all font-mono text-xs">{f.name}</span>
                      <span className="block text-xs text-muted-foreground">
                        {f.problem ?? `${bytes(f.size_bytes)} download · reserves about ${mb(f.min_ram_mb)} RAM`}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
              <label className="flex items-start gap-2">
                <input type="checkbox" className="mt-1" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} />
                <span>
                  I may use this model under its license{preview.license ? ` (${preview.license})` : ''}, and I am responsible
                  for how I use it and its output. AgentMesh has not reviewed it.
                </span>
              </label>
              <Button onClick={onImport} disabled={!file || !accepted || importModel.isPending}>
                {importModel.isPending ? 'Importing…' : 'Import model'}
              </Button>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function CommunityModels() {
  const { data: models } = useCommunityModels();
  const withdraw = useWithdrawCommunityModel();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your models from Hugging Face</CardTitle>
        <CardDescription>
          Import a public GGUF model for your own deployments. Only you can see or deploy it. It runs with llama.cpp on
          nodes whose providers accept community models, from a file pinned to one commit and checked by SHA-256. Gated,
          private, and non-commercially licensed models cannot be imported.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <ImportForm />
        {models && models.length > 0 && (
          <ul className="divide-y divide-border">
            {models.map((m) => {
              const art = m.artifacts[0];
              return (
                <li key={m.id} className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm" data-testid="community-model">
                  <span className="min-w-0">
                    <span className="font-medium">{m.name}</span>{' '}
                    {m.is_community ? <Pill tone="amber">unreviewed</Pill> : <Pill tone="green">in catalog</Pill>}
                    <span className="block text-xs text-muted-foreground">
                      {[m.license, m.download_size_mb && `${mb(m.download_size_mb)} file`, art && `reserves ${mb(art.min_ram_mb)} RAM`]
                        .filter(Boolean)
                        .join(' · ')}
                      {m.source_url && (
                        <>
                          {' · '}
                          <a href={m.source_url} target="_blank" rel="noreferrer noopener" className="underline underline-offset-4">
                            source
                          </a>
                        </>
                      )}
                    </span>
                  </span>
                  <span className="flex gap-2">
                    {art?.is_enabled ? (
                      <Link href={`/customer/deployments/new?model=${m.id}`} className={buttonVariants({ size: 'sm' })}>
                        Deploy
                      </Link>
                    ) : (
                      <span className="text-xs text-muted-foreground">Disabled by an operator</span>
                    )}
                    {m.is_community && (
                      <ConfirmButton
                        size="sm"
                        variant="ghost"
                        confirmLabel="Remove"
                        disabled={withdraw.isPending}
                        onConfirm={() =>
                          withdraw
                            .mutateAsync(m.id)
                            .then(() => toast.success('Model removed'))
                            .catch((e) => toast.error(errorMessage(e)))
                        }
                      >
                        Remove
                      </ConfirmButton>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
