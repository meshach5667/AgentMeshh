'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Notice } from '@/components/common/Notices';
import api from '@/lib/api';
import { errorMessage } from '@/lib/errors';
import type { Deployment } from '@/types';

interface ChatCompletion {
  choices?: { message?: { content?: string } }[];
  usage?: { prompt_tokens?: number; completion_tokens?: number };
}

/** Sends one real, non-streaming request through the gateway with the signed-in user's session. It is metered
 * like any other request and is answered by the model on the provider's node. */
export function Playground({ deployment }: { deployment: Deployment }) {
  const qc = useQueryClient();
  const [prompt, setPrompt] = useState('');
  const run = useMutation({
    mutationFn: async (text: string) => {
      const started = performance.now();
      const { data } = await api.post<ChatCompletion>(
        `${deployment.openai_base_url}/chat/completions`,
        { model: deployment.model_tag, messages: [{ role: 'user', content: text }], max_tokens: 256, stream: false },
        { timeout: 120000 },
      );
      return { data, ms: Math.round(performance.now() - started) };
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ['usage'] }),
  });
  const answer = run.data?.data.choices?.[0]?.message?.content;
  const usage = run.data?.data.usage;

  return (
    <form
      className="space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (prompt.trim()) run.mutate(prompt.trim());
      }}
    >
      <Textarea
        aria-label="Prompt"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        placeholder="Ask the model something (do not include anything confidential)"
        rows={3}
        maxLength={4000}
      />
      <Button type="submit" disabled={run.isPending || !prompt.trim()}>
        {run.isPending ? 'Waiting for the model…' : 'Send'}
      </Button>
      {run.error && <Notice tone="danger">{errorMessage(run.error)}</Notice>}
      {run.data && (
        <div className="space-y-2 rounded-lg border border-border p-4" data-testid="playground-answer">
          <p className="whitespace-pre-wrap text-sm">{answer ?? '(the model returned no text)'}</p>
          <p className="text-xs text-muted-foreground">
            {run.data.ms} ms
            {usage?.completion_tokens != null &&
              ` · ${usage.prompt_tokens ?? '?'} input / ${usage.completion_tokens} output tokens (reported by the runtime)`}
            {' · max 256 output tokens'}
          </p>
        </div>
      )}
    </form>
  );
}
