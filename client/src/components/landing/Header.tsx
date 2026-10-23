import Link from 'next/link';
import { Logo } from '@/components/brand/Logo';
import { ThemeToggle } from '@/components/ui/ThemeToggle';
import { HeaderAuthLinks } from './HeaderAuthLinks';

const NAV = [
  { href: '#product', label: 'Product' },
  { href: '#how-it-works', label: 'How it works' },
  { href: '#pricing', label: 'Pricing' },
  { href: '#trust', label: 'Trust model' },
  { href: '/docs', label: 'Docs' },
];

export function Header() {
  return (
    <header className="fixed inset-x-0 top-0 z-50 border-b border-border/60 bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6">
        <div className="flex items-center gap-10">
          <Logo />
          <nav className="hidden gap-7 md:flex">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} className="text-[13px] text-muted-foreground transition-colors hover:text-foreground">
                {n.label}
              </Link>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle className="rounded-lg" />
          <HeaderAuthLinks />
        </div>
      </div>
    </header>
  );
}
