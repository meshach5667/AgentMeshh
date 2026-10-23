import type { Metadata } from 'next';
import { AuthShell } from '@/components/auth/AuthShell';
import { RedirectIfSignedIn } from '@/components/auth/SessionLinks';
import { LoginForm } from '@/components/auth/LoginForm';

export const metadata: Metadata = { title: 'Sign in' };

export default function LoginPage() {
  return (
    <AuthShell>
      <RedirectIfSignedIn />
      <LoginForm />
    </AuthShell>
  );
}
