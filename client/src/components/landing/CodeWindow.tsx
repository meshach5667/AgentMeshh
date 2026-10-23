'use client';

import { useState } from 'react';
import { cn } from '@/lib/utils';

const TABS = {
  python: {
    label: 'Python',
    code: [
      ['k', 'from'], [' ', ' openai '], ['k', 'import'], [' ', ' OpenAI\n\n'],
      [' ', 'client = OpenAI(\n    base_url='], ['s', '"https://agentmesh-riuz.onrender.com/api/v1/deployments/<id>/v1"'], [' ', ',\n    api_key=os.environ['], ['s', '"AGENTMESH_API_KEY"'], [' ', '],\n)\n\n'],
      [' ', 'reply = client.chat.completions.create(\n    model='], ['s', '"qwen2.5:0.5b"'], [' ', ',\n    messages=[{'], ['s', '"role"'], [' ', ': '], ['s', '"user"'], [' ', ', '], ['s', '"content"'], [' ', ': '], ['s', '"Summarise this ticket"'], [' ', '}],\n    stream='], ['k', 'True'], [' ', ',\n)'],
    ],
  },
  curl: {
    label: 'curl',
    code: [
      ['k', 'curl'], [' ', ' https://agentmesh-riuz.onrender.com/api/v1/deployments/<id>/v1/chat/completions \\\n  -H '], ['s', '"Authorization: Bearer $AGENTMESH_API_KEY"'], [' ', ' \\\n  -H '], ['s', '"Content-Type: application/json"'], [' ', ' \\\n  -d '], ['s', `'{"model": "qwen2.5:0.5b", "messages": [{"role": "user", "content": "Hello"}]}'`],
    ],
  },
} as const;

/** A static example of calling a deployment; not live output. */
export function CodeWindow() {
  const [tab, setTab] = useState<keyof typeof TABS>('python');
  return (
    <div className="h-full bg-background">
      <div className="flex items-center justify-between border-b border-border px-4">
        <div className="flex items-center gap-1.5 py-3">
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
          <span className="size-2.5 rounded-full bg-border" />
        </div>
        <div role="tablist" className="flex gap-1">
          {(Object.keys(TABS) as (keyof typeof TABS)[]).map((k) => (
            <button
              key={k}
              role="tab"
              aria-selected={tab === k}
              onClick={() => setTab(k)}
              className={cn('rounded-md px-2.5 py-1 text-xs transition-colors', tab === k ? 'bg-muted font-medium text-foreground' : 'text-muted-foreground hover:text-foreground')}
            >
              {TABS[k].label}
            </button>
          ))}
        </div>
        <span className="hidden text-[11px] text-muted-foreground sm:block">Example</span>
      </div>
      <pre className="overflow-x-auto p-5 font-mono text-[12.5px] leading-6">
        <code>
          {TABS[tab].code.map(([kind, text], i) => (
            <span key={i} className={kind === 'k' ? 'text-brand' : kind === 's' ? 'text-muted-foreground' : 'text-foreground/90'}>
              {text}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
