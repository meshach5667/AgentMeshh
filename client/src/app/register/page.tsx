import type { Metadata } from 'next';
import { AuthShell } from '@/components/auth/AuthShell';
import { RedirectIfSignedIn } from '@/components/auth/SessionLinks';
import { RegisterForm } from '@/components/auth/RegisterForm';

export const metadata: Metadata = { title: 'Create account' };

export default async function RegisterPage({ searchParams }: { searchParams: Promise<{ role?: string }> }) {
  const { role } = await searchParams;
  return (
    <AuthShell>
      <RedirectIfSignedIn />
      <RegisterForm initialRole={role === 'provider' ? 'provider' : 'customer'} />
    </AuthShell>
  );
}
