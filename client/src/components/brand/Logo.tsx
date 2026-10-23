import Link from 'next/link';
import { cn } from '@/lib/utils';

export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden className={cn('size-7', className)}>
      <rect width="32" height="32" rx="9" className="fill-foreground" />
      <g className="stroke-background" strokeWidth="2.2" strokeLinecap="round" fill="none">
        <path d="M10 21.5 16 10l6 11.5H10Z" opacity="0.55" />
      </g>
      <g className="fill-background">
        <circle cx="16" cy="10" r="3" />
        <circle cx="10" cy="21.5" r="3" />
      </g>
      <circle cx="22" cy="21.5" r="3" className="fill-brand" />
    </svg>
  );
}

export function Logo({ href = '/', className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={cn('flex items-center gap-2.5 font-semibold tracking-tight', className)} aria-label="AgentMesh home">
      <LogoMark />
      <span className="text-[15px]">AgentMesh</span>
    </Link>
  );
}
