import Link from 'next/link';
import { Logo } from '@/components/brand/Logo';

const COLUMNS = [
  { title: 'Product', links: [['/register', 'Deploy a model'], ['/register?role=provider', 'Become a provider'], ['#pricing', 'Pricing']] },
  { title: 'Network', links: [['#status', 'What works today'], ['#trust', 'Trust model'], ['/login', 'Sign in']] },
  { title: 'Docs', links: [['/docs/getting-started', 'Getting started'], ['/docs/api', 'API reference'], ['/docs/providers', 'Provider guide'], ['/docs/security', 'Security']] },
];

export function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-10 px-6 py-14 md:flex-row md:justify-between">
        <div className="max-w-xs">
          <Logo />
          <p className="mt-4 text-sm text-muted-foreground">Open-weight models on community hardware, behind an API you already know.</p>
        </div>
        <div className="grid grid-cols-2 gap-10 sm:flex sm:gap-16">
          {COLUMNS.map((c) => (
            <div key={c.title}>
              <h4 className="text-[13px] font-medium">{c.title}</h4>
              <ul className="mt-4 space-y-2.5 text-[13px] text-muted-foreground">
                {c.links.map(([href, label]) => (
                  <li key={href}>
                    <Link href={href} className="transition-colors hover:text-foreground">
                      {label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
      <div className="border-t border-border">
        <p className="mx-auto max-w-6xl px-6 py-6 text-xs text-muted-foreground">© {new Date().getFullYear()} AgentMesh</p>
      </div>
    </footer>
  );
}
