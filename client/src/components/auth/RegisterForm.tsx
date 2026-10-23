'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Box, Eye, EyeOff, Loader2, Server } from 'lucide-react';
import toast from 'react-hot-toast';
import { cn } from '@/lib/utils';
import type { UserRole } from '@/types/user';
import { useAuth } from '../../hooks/useAuth';
import { Field, inputClass, submitClass } from './AuthShell';

const ROLES = [
  { value: 'customer' as const, icon: Box, title: 'Deploy models', body: 'Run open-weight models behind an API' },
  { value: 'provider' as const, icon: Server, title: 'Provide compute', body: 'Earn from your idle machines' },
];

export function RegisterForm({ initialRole = 'customer' }: { initialRole?: 'provider' | 'customer' }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [role, setRole] = useState<'provider' | 'customer'>(initialRole);
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const { register, error, clearError } = useAuth();
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    if (password !== confirmPassword) {
      toast.error('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      toast.error('Password must be at least 8 characters');
      return;
    }
    setSubmitting(true);
    try {
      await register(email, password, role as UserRole);
      toast.success('Account created');
      router.push(role === 'provider' ? '/provider' : '/customer');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Registration failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <p className="mb-3 font-mono text-xs uppercase tracking-wider text-muted-foreground">Get started</p>
      <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-[34px]">Create your account</h1>
      <p className="mt-2 text-sm text-muted-foreground">Free to join. Pay only for what you deploy.</p>
      {error && (
        <div role="alert" className="mt-6 border-l-2 border-destructive/70 py-1 pl-3 text-sm text-destructive">
          {error}
        </div>
      )}
      <form onSubmit={handleSubmit} className="mt-8 space-y-5">
        <fieldset>
          <legend className="mb-2 text-[13px] font-medium text-foreground/85">Choose how you&apos;ll use AgentMesh</legend>
          <div className="grid grid-cols-2 gap-2">
            {ROLES.map(({ value, icon: Icon, title, body }) => (
              <button
                key={value}
                type="button"
                aria-pressed={role === value}
                onClick={() => setRole(value)}
                className={cn(
                  'min-h-[92px] rounded-lg border px-3 py-2.5 text-left transition-colors',
                  role === value ? 'border-foreground bg-card text-foreground ring-1 ring-foreground' : 'border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground',
                )}
              >
                <span className="flex items-center gap-2">
                  <Icon className={cn('size-4', role === value ? 'text-foreground' : 'text-muted-foreground')} />
                  <span className="text-[13px] font-semibold">{title}</span>
                </span>
                <span className="mt-2 block text-[11px] leading-snug text-muted-foreground">{body}</span>
              </button>
            ))}
          </div>
        </fieldset>
        <Field label="Email">
          <input type="email" autoComplete="email" placeholder="you@company.com" value={email} onChange={(e) => setEmail(e.target.value)} required className={inputClass} />
        </Field>
        <Field label="Password">
          <span className="relative block">
            <input
              type={showPassword ? 'text' : 'password'}
              autoComplete="new-password"
              placeholder="At least 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              className={`${inputClass} pr-10`}
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
            >
              {showPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
            </button>
          </span>
        </Field>
        <Field label="Confirm password">
          <input type="password" autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} required className={inputClass} />
        </Field>
        <button type="submit" disabled={submitting} className={submitClass}>
          {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
          {submitting ? 'Creating account…' : 'Create account'}
          {!submitting && <ArrowRight className="size-4" />}
        </button>
      </form>
      <p className="mt-8 text-center text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link href="/login" className="font-medium text-foreground underline underline-offset-4 decoration-border hover:decoration-foreground">
          Sign in
        </Link>
      </p>
    </div>
  );
}
