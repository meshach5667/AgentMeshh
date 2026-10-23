import type { Metadata } from 'next';
import { DocsShell } from '@/components/docs/DocsShell';

export const metadata: Metadata = {
  title: { default: 'Documentation', template: '%s · AgentMesh docs' },
  description: 'Guides for AgentMesh customers, providers, developers and operators.',
};

export default function DocsLayout({ children }: { children: React.ReactNode }) {
  return <DocsShell>{children}</DocsShell>;
}
