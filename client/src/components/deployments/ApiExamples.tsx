'use client';

import { useState } from 'react';
import { CodeBlock } from '@/components/common/CodeBlock';
import { apiExamples } from '@/lib/deployments';
import type { Deployment } from '@/types';

export function ApiExamples({ deployment }: { deployment: Deployment }) {
  const examples = apiExamples(deployment);
  const [active, setActive] = useState(examples[0]?.id);
  const current = examples.find((e) => e.id === active) ?? examples[0];
  if (!current) return null;
  return (
    <div className="space-y-3">
      <div role="tablist" className="flex flex-wrap gap-1">
        {examples.map((e) => (
          <button
            key={e.id}
            role="tab"
            type="button"
            aria-selected={e.id === current.id}
            onClick={() => setActive(e.id)}
            className={`rounded-md px-3 py-1 text-sm ${e.id === current.id ? 'bg-muted font-medium' : 'text-muted-foreground hover:text-foreground'}`}
          >
            {e.label}
          </button>
        ))}
      </div>
      <CodeBlock code={current.code} />
    </div>
  );
}
