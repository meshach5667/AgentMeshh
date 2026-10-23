'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { ArrowRight, Eye, EyeOff, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { homeFor } from '@/lib/roles';
import { useAuth } from '../../hooks/useAuth';
import { Field, inputClass, submitClass } from './AuthShell';

export function LoginForm() {
  const { login, error, clearError } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearError();
    setSubmitting(true);
    try {
      await login(email, password);
      const { useAuthStore } = await import('../../stores/authStore');
      router.push(homeFor(useAuthStore.getState().user?.role));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <p className="mb-3 font-mono text-xs uppercase tracking-wider text-muted-foreground">Your workspace</p>
      <h1 className="text-3xl font-semibold tracking-[-0.045em] sm:text-[34px]">Welcome back</h1>
      <p className="mt-2 text-sm text-muted-foreground">Sign in to continue to AgentMesh.</p>
      {error && (
        <div role="alert" className="mt-6 border-l-2 border-destructive/70 py-1 pl-3 text-sm text-destructive">
          {error}
        </div>
      )}
      <form onSubmit={handleSubmit} className="mt-9 space-y-5">
        <Field label="Email">
          <input type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required placeholder="you@company.com" className={inputClass} />
        </Field>
        <Field label="Password">
          <span className="relative block">
            <input
              type={showPassword ? 'text' : 'password'}
              autoComplete="current-password"
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
        <button type="submit" disabled={submitting} className={submitClass}>
          {submitting ? <Loader2 className="size-4 animate-spin" /> : null}
          {submitting ? 'Signing in…' : 'Sign in'}
          {!submitting && <ArrowRight className="size-4" />}
        </button>
      </form>
      <p className="mt-8 text-center text-sm text-muted-foreground">
        New to AgentMesh?{' '}
        <Link href="/register" className="font-medium text-foreground underline underline-offset-4 decoration-border hover:decoration-foreground">
          Create an account
        </Link>
      </p>
    </div>
  );
}
