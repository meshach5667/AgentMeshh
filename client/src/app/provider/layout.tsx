import { AuthGuard } from '@/components/auth/AuthGuard';
import { DashboardLayout } from '@/components/layout/DashboardLayout';

export default function ProviderLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard roles={['provider']}>
      <DashboardLayout>{children}</DashboardLayout>
    </AuthGuard>
  );
}
